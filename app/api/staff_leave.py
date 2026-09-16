"""Signed public receipt images; separately manager-authenticated review UI/API."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.staff_leave import StaffLeaveRequest
from app.services.cf_access_service import get_cf_access_email
from app.services import staff_leave
from app.services.staff_leave_image import render_png

image_router = APIRouter()
admin_router = APIRouter()
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                   "X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer"}


def require_leave_manager(request: Request) -> str:
    # This existing helper verifies the JWT AND the manager allowlist.
    # Staff-tier Access, a shared kiosk, and a forged email header are not sufficient.
    email = get_cf_access_email(request)
    if not email:
        raise HTTPException(403, "กรุณาเข้าสู่ระบบด้วยบัญชีผู้จัดการ")
    return email


@image_router.get("/leave-images/{request_id}.png")
def receipt_image(request_id: str, version: int = Query(..., ge=1),
                  expires: int = Query(...), signature: str = Query(..., max_length=64),
                  db: Session = Depends(get_db)):
    if not staff_leave.valid_image_token(request_id, version, expires, signature):
        raise HTTPException(404, "Not found", headers=PRIVATE_HEADERS)
    row = db.get(StaffLeaveRequest, request_id)
    if row is None or row.version != version:
        raise HTTPException(404, "Not found", headers=PRIVATE_HEADERS)
    png = render_png(row, datetime.fromtimestamp(expires - staff_leave.IMAGE_TTL, timezone.utc))
    return Response(png, media_type="image/png", headers=PRIVATE_HEADERS)


def _dto(row: StaffLeaveRequest) -> dict:
    return {"id": row.id, "reference": staff_leave.reference(row),
            "employee_name": row.employee_name, "department": row.department,
            "location": row.location, "leave_type": row.leave_type,
            "leave_label": staff_leave.TYPES[row.leave_type],
            "date_from": row.date_from.isoformat(), "date_to": row.date_to.isoformat(),
            "calendar_days": (row.date_to - row.date_from).days + 1,
            "status": row.status, "status_label": staff_leave.STATUSES[row.status],
            "version": row.version, "created_at": row.created_at.isoformat() + "Z",
            "reviewed_by": row.reviewed_by}


@admin_router.get("")
def list_requests(response: Response, status: Literal["pending", "approved", "rejected", "cancelled"] = "pending",
                  limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                  manager: str = Depends(require_leave_manager), db: Session = Depends(get_db)):
    response.headers.update(PRIVATE_HEADERS)
    rows = db.query(StaffLeaveRequest).filter(StaffLeaveRequest.status == status).order_by(
        StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()).offset(offset).limit(limit).all()
    return {"items": [_dto(row) for row in rows], "limit": limit, "offset": offset}


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    version: int = Field(..., ge=1)


@admin_router.post("/{request_id}/decision")
def review(request_id: str, body: Decision, request: Request, response: Response,
           x_hf_leave_action: str = Header(default=""),
           manager: str = Depends(require_leave_manager), db: Session = Depends(get_db)):
    if (x_hf_leave_action != "review" or
            request.headers.get("origin", staff_leave.ORIGIN) != staff_leave.ORIGIN):
        raise HTTPException(403, "Invalid request origin")
    try:
        row = staff_leave.decide(db, request_id, body.decision, body.version, manager)
    except staff_leave.LeaveError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    response.headers.update(PRIVATE_HEADERS)
    return _dto(row)


@admin_router.get("/manage", response_class=HTMLResponse)
def manage(manager: str = Depends(require_leave_manager)):
    return HTMLResponse(MANAGE_HTML, headers={**PRIVATE_HEADERS, "Content-Security-Policy":
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})


MANAGE_HTML = """<!doctype html><html lang="th"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HF ภายใน • พิจารณาใบลา</title>
<style>
body{font-family:system-ui,sans-serif;background:#f3f6f4;color:#17352f;margin:0;padding:24px}
main{max-width:900px;margin:auto}h1{margin-bottom:8px}p{line-height:1.7}
.card{background:white;border:1px solid #d8e4dd;border-radius:14px;padding:20px;margin:16px 0}
button,select{font:inherit;padding:12px;margin:4px;border-radius:8px;border:1px solid #acbeb4;cursor:pointer}
button{background:#17694f;color:white}button.reject{background:#a13030}button:disabled{opacity:.5;cursor:wait}
.ref{overflow-wrap:anywhere;color:#52655f;font-size:14px}#message{white-space:pre-wrap}a{color:#17694f}
</style><main><h1>HF ภายใน • พิจารณาใบลา</h1>
<p>ตรวจสอบสิทธิวันลาและตารางงานก่อนอนุมัติ จำนวนวันเป็นวันตามปฏิทิน ไม่ใช่ยอดสิทธิวันลา
ระบบจะลงวันลาในตารางงานเฉพาะรายการที่อนุมัติ และไม่เขียนทับวันที่มีวันลาเดิม</p>
<p><a href="/fingerprintlogs/v2/shifts-admin">เปิดตารางงาน</a></p>
<label>สถานะ <select id="status"><option value="pending">รออนุมัติ</option>
<option value="approved">อนุมัติแล้ว</option><option value="rejected">ไม่อนุมัติ</option>
<option value="cancelled">ยกเลิกแล้ว</option></select></label><button id="refresh">โหลดใหม่</button>
<p id="message" role="status"></p><div id="items"></div><button id="more" hidden>รายการถัดไป</button></main>
<script>
'use strict';
const base='/api/private/leaves/requests';
const items=document.getElementById('items'),message=document.getElementById('message');
const status=document.getElementById('status'),more=document.getElementById('more');
let offset=0,generation=0;
function el(tag,text,cls){const x=document.createElement(tag);x.textContent=text;if(cls)x.className=cls;return x;}
function dateTH(d){const [y,m,day]=d.split('-');return `${day}/${m}/${Number(y)+543}`;}
async function api(path,options={}){
 const r=await fetch(base+path,{...options,credentials:'same-origin',headers:{'Accept':'application/json',...options.headers}});
 if(!r.ok){let text='ไม่สามารถโหลดข้อมูล กรุณาเข้าสู่ระบบด้วยบัญชีผู้จัดการ';try{const body=await r.json();if(typeof body.detail==='string')text=body.detail;}catch{}throw new Error(text);}
 return r.json();
}
function card(row){
 const box=el('section','','card');box.append(el('h2',row.employee_name));
 box.append(el('p',`${row.department||'ไม่ระบุแผนก'} • ${row.location||'ไม่ระบุสาขา'}`));
 box.append(el('p',`${row.leave_label} • ${dateTH(row.date_from)} – ${dateTH(row.date_to)} • ${row.calendar_days} วันตามปฏิทิน`));
 box.append(el('p',row.status_label));box.append(el('p',row.reference,'ref'));
 if(row.reviewed_by)box.append(el('p',`ผู้พิจารณา: ${row.reviewed_by}`,'ref'));
 if(row.status==='pending')for(const [decision,label] of [['approved','อนุมัติ'],['rejected','ไม่อนุมัติ']]){
  const button=el('button',label,decision==='rejected'?'reject':'');
  button.onclick=async()=>{
   if(!confirm(`${label}ใบลาของ ${row.employee_name} วันที่ ${dateTH(row.date_from)} – ${dateTH(row.date_to)}?`))return;
   box.querySelectorAll('button').forEach(b=>b.disabled=true);
   try{await api(`/${row.id}/decision`,{method:'POST',headers:{'Content-Type':'application/json','X-HF-Leave-Action':'review'},body:JSON.stringify({decision,version:row.version})});await load();}
   catch(e){message.textContent=e.message;box.querySelectorAll('button').forEach(b=>b.disabled=false);}
  };box.append(button);
 }
 return box;
}
async function load(append=false){
 const current=++generation;message.textContent='กำลังโหลด…';more.disabled=true;
 if(!append){offset=0;items.replaceChildren();more.hidden=true;}
 try{const data=await api(`?status=${encodeURIComponent(status.value)}&limit=100&offset=${offset}`);
  if(current!==generation)return;
  for(const row of data.items)items.append(card(row));offset+=data.items.length;
  more.hidden=data.items.length<100;message.textContent=offset?`แสดง ${offset} รายการ`:'ไม่มีรายการในสถานะนี้';
 }catch(e){if(current===generation)message.textContent=e.message;}
 finally{if(current===generation)more.disabled=false;}
}
status.onchange=()=>load();document.getElementById('refresh').onclick=()=>load();more.onclick=()=>load(true);load();
</script></html>"""

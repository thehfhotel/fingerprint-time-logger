(function () {
  "use strict";

  var V2 = window.V2;
  var nav = document.getElementById("v2nav");
  if (!V2 || !nav) return;

  var page = (nav.getAttribute("data-page") || "").trim();
  if (page !== "shifts-admin" && page !== "monthly") return;

  var TYPES = [
    { code: "vacation", label: "ลาพักร้อน", short: "พร", color: "#EAF6EF" },
    { code: "personal", label: "ลากิจ", short: "กจ", color: "#FBF3E1" },
    { code: "sick", label: "ลาป่วย", short: "ปว", color: "#FBEAEA" },
    { code: "day_off", label: "ใช้วันหยุด", short: "ชห", color: "#E8E4DF" },
    { code: "public_holiday", label: "วันหยุดนักขัตฤกษ์", short: "นข", color: "#CFC9C1" },
  ];
  var PORTIONS = {
    full: "เต็มวัน",
    am: "ครึ่งวันเช้า",
    pm: "ครึ่งวันบ่าย",
  };
  var TYPE_BY_CODE = {};
  TYPES.forEach(function (t) { TYPE_BY_CODE[t.code] = t; });

  function esc(value) {
    return V2.escapeHtml(String(value == null ? "" : value));
  }

  function startOfMonth(ymd) {
    return String(ymd || V2.bangkokDate()).slice(0, 7) + "-01";
  }

  function monthEnd(start) {
    return V2.addDays(V2.addMonths(start, 1), -1);
  }

  function thaiDate(iso) {
    if (!iso) return "—";
    var parts = String(iso).split("-").map(Number);
    if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2]) return String(iso);
    var dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    var wd = V2.WEEKDAY_TH_SHORT[dt.getUTCDay()] || "";
    return wd + " " + String(parts[2]).padStart(2, "0") + "/" +
      String(parts[1]).padStart(2, "0") + "/" + (parts[0] + 543);
  }

  function portionLabel(row) {
    return PORTIONS[row && row.leave_portion] || PORTIONS.full;
  }

  function leaveWeight(row) {
    return row && (row.leave_portion === "am" || row.leave_portion === "pm") ? 0.5 : 1;
  }

  function typeMeta(code) {
    return TYPE_BY_CODE[code] || { code: code, label: code || "วันลา", short: "ลา", color: "#F4F1ED" };
  }

  function setTextStatus(node, text, kind) {
    if (!node) return;
    var color = kind === "bad" ? "#7F1F1F" : kind === "good" ? "#1D5438" : "#7A7268";
    node.style.color = color;
    node.textContent = text || "";
  }

  async function fetchEmployees() {
    var payload = await V2.apiFetch("/api/private/employees/?include_hidden=true");
    return (payload && payload.employees) || [];
  }

  async function fetchLeaves(start) {
    return (await V2.apiFetch(
      "/api/private/leaves/employee?from=" + encodeURIComponent(start) +
      "&to=" + encodeURIComponent(monthEnd(start))
    )) || [];
  }

  async function fetchHolidays(start) {
    return (await V2.apiFetch(
      "/api/private/leaves/holidays?from=" + encodeURIComponent(start) +
      "&to=" + encodeURIComponent(monthEnd(start))
    )) || [];
  }

  function employeeNameMap(employees) {
    var out = {};
    (employees || []).forEach(function (e) {
      out[e.badge_number] = e.display_name || e.thai_name || e.badge_number;
    });
    return out;
  }

  function employeeOptions(employees) {
    var sorted = (employees || []).slice().sort(function (a, b) {
      return String(a.display_name || a.badge_number || "").localeCompare(
        String(b.display_name || b.badge_number || ""), "th"
      );
    });
    return '<option value="">— เลือกพนักงาน —</option>' + sorted.map(function (e) {
      return '<option value="' + esc(e.badge_number) + '">' +
        esc((e.display_name || e.badge_number) + " (#" + e.badge_number + ")") +
        '</option>';
    }).join("");
  }

  // ---------------------------------------------------------------------
  // shifts-admin: authoritative employee leave board
  // ---------------------------------------------------------------------

  function installShiftsAdmin() {
    var oldBoard = document.getElementById("lbBoard");
    if (!oldBoard || document.getElementById("leaveSyncBoard")) return;

    // The legacy board understands only four full-day types. Keep its month
    // controls/events for backwards compatibility, but replace its visible
    // contents with the shared EmployeeLeave view below.
    oldBoard.style.display = "none";
    var oldError = document.getElementById("lbError");
    if (oldError) oldError.style.display = "none";

    var board = document.createElement("div");
    board.id = "leaveSyncBoard";
    board.className = "space-y-3";
    oldBoard.insertAdjacentElement("afterend", board);

    var monthStart = startOfMonth(V2.bangkokDate());
    var employees = [];
    var leaves = [];
    var busy = false;

    function setPeriodLabel() {
      var node = document.getElementById("lbPeriodLabel");
      if (node) node.textContent = V2.monthLabelTH(monthStart);
    }

    async function reload() {
      if (busy) return;
      busy = true;
      setPeriodLabel();
      board.innerHTML =
        '<div class="rounded-xl border border-ink-200 bg-white px-5 py-8 text-center text-sm text-ink-500 shadow-card">' +
        'กำลังโหลดวันลา…</div>';
      try {
        var result = await Promise.all([fetchEmployees(), fetchLeaves(monthStart)]);
        employees = result[0];
        leaves = result[1];
        render();
      } catch (err) {
        board.innerHTML =
          '<div class="rounded-xl border border-bad-100 bg-bad-50 px-4 py-3 text-sm text-bad-700">' +
          'โหลดวันลาไม่สำเร็จ (' + esc(err.status || "เครือข่าย") + ')' +
          ' <button type="button" id="leaveSyncRetry" class="font-semibold underline underline-offset-2">ลองใหม่</button></div>';
        var retry = document.getElementById("leaveSyncRetry");
        if (retry) retry.addEventListener("click", reload);
      } finally {
        busy = false;
      }
    }

    function render() {
      var names = employeeNameMap(employees);
      var byType = {};
      TYPES.forEach(function (t) { byType[t.code] = []; });
      leaves.forEach(function (l) {
        if (!byType[l.leave_type]) byType[l.leave_type] = [];
        byType[l.leave_type].push(l);
      });

      var info = document.createElement("div");
      info.className = "rounded-xl border border-ink-200 bg-white px-4 py-3 shadow-card";
      info.innerHTML =
        '<p class="text-sm font-semibold text-ink-900">ข้อมูลเดียวกับ HF ภายในและรายงานรายเดือน</p>' +
        '<p class="mt-0.5 text-xs text-ink-500">รองรับเต็มวัน ครึ่งวันเช้า ครึ่งวันบ่าย และใช้วันหยุด · ครึ่งวันไม่ลบกะของวันนั้น</p>';

      var grid = document.createElement("div");
      grid.className = "grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5";

      TYPES.forEach(function (type) {
        var items = (byType[type.code] || []).slice().sort(function (a, b) {
          return String(a.date).localeCompare(String(b.date)) ||
            String(names[a.employee_badge_number] || a.employee_badge_number).localeCompare(
              String(names[b.employee_badge_number] || b.employee_badge_number), "th"
            );
        });

        var card = document.createElement("section");
        card.className = "flex min-w-0 flex-col rounded-xl border border-ink-200 bg-white shadow-card";

        var head = document.createElement("div");
        head.className = "flex items-center gap-2 border-b border-ink-100 px-3 py-2";
        head.innerHTML =
          '<span class="inline-block h-3 w-3 rounded" style="background:' + type.color + '"></span>' +
          '<span class="min-w-0 flex-1 truncate text-sm font-semibold text-ink-800">' + esc(type.label) + '</span>' +
          '<span class="rounded-full bg-ink-100 px-2 py-0.5 text-xs text-ink-500">' + items.length + '</span>';
        card.appendChild(head);

        var body = document.createElement("div");
        body.className = "flex-1 space-y-1.5 p-2 min-h-[4rem]";
        if (!items.length) {
          body.innerHTML = '<p class="px-1 py-4 text-center text-xs text-ink-500">ยังไม่มีรายการ</p>';
        } else {
          items.forEach(function (l) {
            var row = document.createElement("div");
            row.className = "rounded-lg border border-ink-100 bg-ink-50/40 px-2 py-1.5";
            row.style.borderLeft = "3px solid " + type.color;
            row.innerHTML =
              '<div class="flex items-start gap-2">' +
                '<div class="min-w-0 flex-1">' +
                  '<div class="truncate text-sm font-medium text-ink-800">' +
                    esc(names[l.employee_badge_number] || ("#" + l.employee_badge_number)) +
                  '</div>' +
                  '<div class="text-[11px] text-ink-500">' + esc(thaiDate(l.date)) + '</div>' +
                  '<div class="mt-0.5 text-[11px] font-semibold text-ink-700">' + esc(portionLabel(l)) + '</div>' +
                '</div>' +
                '<button type="button" class="leave-sync-delete shrink-0 rounded-md px-1.5 py-1 text-xs text-ink-500 hover:bg-bad-50 hover:text-bad-700" aria-label="ลบ">ลบ</button>' +
              '</div>' +
              '<span class="leave-sync-row-status block text-[11px]"></span>';
            var del = row.querySelector(".leave-sync-delete");
            var rowStatus = row.querySelector(".leave-sync-row-status");
            del.addEventListener("click", async function () {
              if (!window.confirm("ยืนยันลบ " + type.label + " ของ " +
                  (names[l.employee_badge_number] || l.employee_badge_number) +
                  " วันที่ " + thaiDate(l.date) + " ?")) return;
              del.disabled = true;
              setTextStatus(rowStatus, "กำลังลบ…", "muted");
              try {
                await V2.apiFetch(
                  "/api/private/leaves/employee/" + encodeURIComponent(l.employee_badge_number) + "/" + l.date,
                  { method: "DELETE" }
                );
                await reload();
              } catch (err) {
                del.disabled = false;
                setTextStatus(rowStatus, "ลบไม่สำเร็จ (" + (err.status || "เครือข่าย") + ")", "bad");
              }
            });
            body.appendChild(row);
          });
        }
        card.appendChild(body);

        var foot = document.createElement("div");
        foot.className = "space-y-1.5 border-t border-ink-100 p-2";
        foot.innerHTML =
          '<select class="leave-sync-employee h-10 w-full rounded-lg border border-ink-200 bg-white px-2 text-xs">' +
            employeeOptions(employees) +
          '</select>' +
          '<input type="date" class="leave-sync-date h-10 w-full rounded-lg border border-ink-300 bg-white px-2 text-xs" />' +
          '<select class="leave-sync-portion h-10 w-full rounded-lg border border-ink-200 bg-white px-2 text-xs">' +
            '<option value="full">เต็มวัน</option>' +
            '<option value="am">ครึ่งวันเช้า</option>' +
            '<option value="pm">ครึ่งวันบ่าย</option>' +
          '</select>' +
          '<button type="button" class="leave-sync-add btn-primary h-10 text-xs">เพิ่ม' + esc(type.label) + '</button>' +
          '<span class="leave-sync-status block min-h-[1rem] text-[11px] text-ink-500"></span>';
        var empSel = foot.querySelector(".leave-sync-employee");
        var dateInput = foot.querySelector(".leave-sync-date");
        var portionSel = foot.querySelector(".leave-sync-portion");
        var add = foot.querySelector(".leave-sync-add");
        var statusNode = foot.querySelector(".leave-sync-status");
        dateInput.value = monthStart;
        dateInput.min = monthStart;
        dateInput.max = monthEnd(monthStart);
        add.addEventListener("click", async function () {
          if (!empSel.value) {
            setTextStatus(statusNode, "เลือกพนักงานก่อน", "bad");
            return;
          }
          if (!dateInput.value) {
            setTextStatus(statusNode, "เลือกวันที่ก่อน", "bad");
            return;
          }
          add.disabled = true;
          setTextStatus(statusNode, "กำลังบันทึก…", "muted");
          try {
            await V2.apiFetch("/api/private/leaves/employee", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                employee_badge_number: empSel.value,
                leave_type: type.code,
                leave_portion: portionSel.value,
                date: dateInput.value,
              }),
            });
            await reload();
          } catch (err) {
            add.disabled = false;
            setTextStatus(statusNode, "เพิ่มไม่สำเร็จ (" + (err.status || "เครือข่าย") + ")", "bad");
          }
        });
        card.appendChild(foot);
        grid.appendChild(card);
      });

      board.innerHTML = "";
      board.appendChild(info);
      board.appendChild(grid);
    }

    function moveMonth(delta) {
      monthStart = startOfMonth(V2.addMonths(monthStart, delta));
      reload();
    }
    var prev = document.getElementById("lbPrev");
    var next = document.getElementById("lbNext");
    var current = document.getElementById("lbThisMonth");
    var retry = document.getElementById("lbRetry");
    if (prev) prev.addEventListener("click", function () { moveMonth(-1); });
    if (next) next.addEventListener("click", function () { moveMonth(1); });
    if (current) current.addEventListener("click", function () {
      monthStart = startOfMonth(V2.bangkokDate());
      reload();
    });
    if (retry) retry.addEventListener("click", reload);

    // Refresh when the tab is opened. This also picks up a leave created in
    // HF ภายใน while the page was already open.
    var tab = document.querySelector('.tab[data-tab="leaveboard"]');
    if (tab) tab.addEventListener("click", reload);

    reload();
  }

  // ---------------------------------------------------------------------
  // monthly: explicit leave/holiday panel alongside attendance totals
  // ---------------------------------------------------------------------

  function installMonthly() {
    if (document.getElementById("monthlyLeaveSync")) return;
    var metaLine = document.getElementById("metaLine");
    var controls = metaLine && metaLine.closest("section");
    if (!controls || !controls.parentNode) return;

    var panel = document.createElement("section");
    panel.id = "monthlyLeaveSync";
    panel.className = "mb-4 rounded-xl border border-ink-200 bg-white p-3 shadow-card md:p-4";
    controls.insertAdjacentElement("afterend", panel);

    var employees = [];
    var leaves = [];
    var holidays = [];
    var loading = false;

    function selectedMonthStart() {
      var dayControls = document.getElementById("dayControls");
      var dayPicker = document.getElementById("datePicker");
      var monthPicker = document.getElementById("monthPicker");
      var value = "";
      if (dayControls && !dayControls.classList.contains("hidden") && dayPicker && dayPicker.value) {
        value = dayPicker.value.slice(0, 7);
      } else if (monthPicker && monthPicker.value) {
        value = monthPicker.value;
      } else if (dayPicker && dayPicker.value) {
        value = dayPicker.value.slice(0, 7);
      }
      return startOfMonth((value || V2.bangkokDate().slice(0, 7)) + "-01");
    }

    function selectedLocation() {
      var active = document.querySelector('.loc-chip.loc-on[data-location]');
      return active ? (active.getAttribute("data-location") || "all") : "all";
    }

    function searchText() {
      var input = document.getElementById("searchInput");
      return input ? String(input.value || "").trim().toLocaleLowerCase("th") : "";
    }

    async function reload() {
      if (loading) return;
      loading = true;
      var start = selectedMonthStart();
      panel.innerHTML =
        '<p class="text-sm font-semibold text-ink-900">วันลา · วันหยุด ' + esc(V2.monthLabelTH(start)) + '</p>' +
        '<p class="mt-1 text-xs text-ink-500">กำลังโหลด…</p>';
      try {
        var result = await Promise.all([fetchEmployees(), fetchLeaves(start), fetchHolidays(start)]);
        employees = result[0];
        leaves = result[1];
        holidays = result[2];
        render(start);
      } catch (err) {
        panel.innerHTML =
          '<div class="flex flex-wrap items-center gap-2">' +
            '<span class="text-sm text-bad-700">โหลดวันลาไม่สำเร็จ (' + esc(err.status || "เครือข่าย") + ')</span>' +
            '<button type="button" id="monthlyLeaveRetry" class="text-sm font-semibold text-brand-700 underline underline-offset-2">ลองใหม่</button>' +
          '</div>';
        var retry = document.getElementById("monthlyLeaveRetry");
        if (retry) retry.addEventListener("click", reload);
      } finally {
        loading = false;
      }
    }

    function render(start) {
      var location = selectedLocation();
      var query = searchText();
      var empByBadge = {};
      employees.forEach(function (e) { empByBadge[e.badge_number] = e; });

      var visible = leaves.filter(function (l) {
        var emp = empByBadge[l.employee_badge_number];
        if (!emp) return false;
        if (location !== "all" && emp.location !== location) return false;
        if (query) {
          var hay = ((emp.display_name || "") + " " + emp.badge_number + " " +
            (typeMeta(l.leave_type).label || "")).toLocaleLowerCase("th");
          if (hay.indexOf(query) === -1) return false;
        }
        return true;
      }).sort(function (a, b) {
        return String(a.date).localeCompare(String(b.date)) ||
          String((empByBadge[a.employee_badge_number] || {}).display_name || a.employee_badge_number)
            .localeCompare(String((empByBadge[b.employee_badge_number] || {}).display_name || b.employee_badge_number), "th");
      });

      var total = visible.reduce(function (sum, row) { return sum + leaveWeight(row); }, 0);
      var head =
        '<div class="flex flex-wrap items-start justify-between gap-2">' +
          '<div>' +
            '<p class="text-sm font-semibold text-ink-900">วันลา · วันหยุด ' + esc(V2.monthLabelTH(start)) + '</p>' +
            '<p class="mt-0.5 text-xs text-ink-500">ข้อมูลเดียวกับ HF ภายในและหน้า จัดกะ · ครึ่งวันนับ 0.5 วัน</p>' +
          '</div>' +
          '<span class="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700">รวม ' +
            esc(Number.isInteger(total) ? String(total) : total.toFixed(1)) + ' วัน</span>' +
        '</div>';

      var rows = "";
      if (!visible.length) {
        rows = '<p class="mt-3 rounded-lg bg-ink-50 px-3 py-4 text-center text-sm text-ink-500">ไม่มีวันลาของพนักงานตามตัวกรองนี้</p>';
      } else {
        rows = '<div class="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">' +
          visible.map(function (l) {
            var emp = empByBadge[l.employee_badge_number] || {};
            var type = typeMeta(l.leave_type);
            return '<div class="rounded-lg border border-ink-100 bg-ink-50/40 px-3 py-2" style="border-left:3px solid ' + type.color + '">' +
              '<div class="flex items-start justify-between gap-2">' +
                '<div class="min-w-0">' +
                  '<p class="truncate text-sm font-semibold text-ink-800">' + esc(emp.display_name || l.employee_badge_number) + '</p>' +
                  '<p class="text-xs text-ink-500">' + esc(thaiDate(l.date)) + '</p>' +
                '</div>' +
                '<span class="shrink-0 rounded bg-white px-1.5 py-0.5 text-[11px] font-semibold text-ink-700">' + esc(portionLabel(l)) + '</span>' +
              '</div>' +
              '<p class="mt-1 text-xs font-semibold text-brand-700">' + esc(type.label) + '</p>' +
            '</div>';
          }).join("") + '</div>';
      }

      var holidayRows = holidays.length
        ? '<div class="mt-3 border-t border-ink-100 pt-2">' +
            '<p class="text-xs font-semibold text-ink-700">วันหยุดบริษัท</p>' +
            '<div class="mt-1 flex flex-wrap gap-1.5">' + holidays.map(function (h) {
              return '<span class="rounded-md bg-ink-100 px-2 py-1 text-xs text-ink-700">' +
                esc(thaiDate(h.date) + " · " + h.name) + '</span>';
            }).join("") + '</div></div>'
        : "";
      panel.innerHTML = head + rows + holidayRows;
    }

    function refreshAfterPageUpdate() {
      window.setTimeout(reload, 0);
    }
    ["prevBtn", "nextBtn", "thisMonthBtn", "prevDayBtn", "nextDayBtn", "todayBtn",
      "viewDayBtn", "viewGridBtn", "viewSheetBtn"].forEach(function (id) {
        var node = document.getElementById(id);
        if (node) node.addEventListener("click", refreshAfterPageUpdate);
      });
    ["monthPicker", "datePicker"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) node.addEventListener("change", reload);
    });
    document.querySelectorAll('.loc-chip[data-location]').forEach(function (node) {
      node.addEventListener("click", refreshAfterPageUpdate);
    });
    var search = document.getElementById("searchInput");
    if (search) search.addEventListener("input", function () {
      var start = selectedMonthStart();
      render(start);
    });

    reload();
  }

  if (page === "shifts-admin") installShiftsAdmin();
  if (page === "monthly") installMonthly();
})();

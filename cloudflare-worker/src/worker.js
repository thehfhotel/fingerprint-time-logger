/**
 * Cloudflare Worker: QR Check-in URL Rewriting Proxy
 *
 * Purpose: Rewrite public QR check-in URLs to internal app structure
 * External: erp.thehfhotel.org/qr-checkin/mobile
 * Internal: http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Only handle /qr-checkin/* paths
    if (!url.pathname.startsWith('/qr-checkin/')) {
      return new Response('Not Found', {
        status: 404,
        headers: { 'Content-Type': 'text/plain' }
      });
    }

    // Rewrite path: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
    const newPath = url.pathname.replace('/qr-checkin/', `${env.PATH_PREFIX}/qr-checkin/`);
    const backendUrl = `http://${env.BACKEND_HOST}:${env.BACKEND_PORT}${newPath}${url.search}`;

    // Create modified request
    const modifiedRequest = new Request(backendUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: 'follow'
    });

    try {
      // Forward to backend
      const response = await fetch(modifiedRequest);

      // Create response with modified headers
      const modifiedResponse = new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers
      });

      // Add security headers for public access
      modifiedResponse.headers.set('X-Content-Type-Options', 'nosniff');
      modifiedResponse.headers.set('X-Frame-Options', 'DENY');
      modifiedResponse.headers.set('X-XSS-Protection', '1; mode=block');
      modifiedResponse.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');

      return modifiedResponse;

    } catch (error) {
      // Log error and return 502 Bad Gateway
      console.error('Backend fetch failed:', error);
      return new Response('Bad Gateway: Unable to reach backend server', {
        status: 502,
        headers: { 'Content-Type': 'text/plain' }
      });
    }
  }
};

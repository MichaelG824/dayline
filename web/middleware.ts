import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE = 'dayline_session';

function allowedEmail(): string {
  return (process.env.ALLOWED_EMAIL ?? '').trim().toLowerCase();
}

function publicUrl(request: NextRequest, pathname: string): URL {
  const url = request.nextUrl.clone();
  const forwardedHost = request.headers.get('x-forwarded-host');
  const host = forwardedHost ?? request.headers.get('host');
  if (host) {
    url.host = host.split(':')[0];
    url.port = host.includes(':') && !host.startsWith('[') ? host.split(':').slice(1).join(':') : '';
  }
  const proto = request.headers.get('x-forwarded-proto');
  if (proto) url.protocol = proto.split(',')[0].trim() + ':';
  url.pathname = pathname;
  url.search = '';
  return url;
}

function emailFromSession(token: string | undefined): string | null {
  if (!token) return null;
  const parts = token.split('.');
  if (parts.length < 2) return null;
  try {
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const json = atob(padded);
    const payload = JSON.parse(json) as { email?: unknown };
    return typeof payload.email === 'string' ? payload.email : null;
  } catch {
    return null;
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const email = emailFromSession(request.cookies.get(SESSION_COOKIE)?.value);
  const configured = allowedEmail();
  // FastAPI is the hard allowlist. If ALLOWED_EMAIL was not inlined into the
  // Edge bundle at build time, skip the UI-side match so a valid session can
  // still load the shell (the API will 403 anyone else).
  const allowed =
    email !== null && (!configured || email.trim().toLowerCase() === configured);

  if (pathname === '/login') {
    if (allowed) return NextResponse.redirect(publicUrl(request, '/'));
    if (email) return NextResponse.redirect(publicUrl(request, '/not-allowed'));
    return NextResponse.next();
  }

  if (pathname === '/not-allowed') {
    if (!email) return NextResponse.redirect(publicUrl(request, '/login'));
    if (allowed) return NextResponse.redirect(publicUrl(request, '/'));
    return NextResponse.next();
  }

  if (!email) {
    return NextResponse.redirect(publicUrl(request, '/login'));
  }
  if (!allowed) {
    return NextResponse.redirect(publicUrl(request, '/not-allowed'));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};

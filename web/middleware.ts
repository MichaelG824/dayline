import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIE = 'dayline_session';

function allowedEmail(): string {
  return (process.env.ALLOWED_EMAIL ?? '').trim().toLowerCase();
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
  const allowed = email !== null && email.trim().toLowerCase() === allowedEmail();

  if (pathname === '/login') {
    if (allowed) return NextResponse.redirect(new URL('/', request.url));
    if (email) return NextResponse.redirect(new URL('/not-allowed', request.url));
    return NextResponse.next();
  }

  if (pathname === '/not-allowed') {
    if (!email) return NextResponse.redirect(new URL('/login', request.url));
    if (allowed) return NextResponse.redirect(new URL('/', request.url));
    return NextResponse.next();
  }

  if (!email) {
    return NextResponse.redirect(new URL('/login', request.url));
  }
  if (!allowed) {
    return NextResponse.redirect(new URL('/not-allowed', request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};

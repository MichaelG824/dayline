const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_LABELS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

// "2026-09-03" -> "Thu, Sep 3"
export function formatDayLabel(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  return `${WEEKDAY_LABELS[d.getDay()]}, ${MONTH_LABELS[d.getMonth()]} ${d.getDate()}`;
}

// ISO datetime -> days from now, floored (can be negative for the past).
export function daysUntil(iso: string): number {
  const target = new Date(iso);
  const now = new Date();
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.ceil((target.getTime() - now.getTime()) / msPerDay);
}

// ISO datetime -> "10:30 AM"
export function formatClockTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

// ISO datetime -> "Tue, Sep 8 at 10:00"
export function formatDateTimeLabel(iso: string): string {
  const d = new Date(iso);
  const day = `${WEEKDAY_LABELS[d.getDay()]}, ${MONTH_LABELS[d.getMonth()]} ${d.getDate()}`;
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  return `${day} at ${time}`;
}

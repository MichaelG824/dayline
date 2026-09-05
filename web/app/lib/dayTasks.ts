import { PlanResponse, TaskRow } from './api';

// A task relevant to the currently viewed day, with its effective time
// resolved: the computed schedule slot if the planner placed it, else the
// last recorded scheduled time (for a task already marked Done, which the
// backend excludes from future plans), else the user-pinned fixedTime, else
// null (not yet timed).
export interface DayTask extends TaskRow {
  effectiveTime: string | null;
}

const WEEKDAY_ORDER = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function isRecurrenceDueOnDay(recurs: string, recurDay: string | null, day: string): boolean {
  const weekday = WEEKDAY_ORDER[new Date(`${day}T00:00:00`).getDay()];
  if (recurs === 'Daily') return true;
  if (recurs === 'Weekdays') return weekday !== 'Sun' && weekday !== 'Sat';
  if (recurs === 'Weekly') return recurDay === weekday;
  return false;
}

// Mirrors the backend's _eligible_tasks() day-membership rule, but - unlike
// the backend, which drops a DONE task from the plan entirely - keeps a task
// visible on the day it was completed if that day is where it belongs (an
// explicit plannedDate, or a recurring task due that day). A plannedDate-less
// "nag until done" backlog task still disappears once Done, matching the
// backend's original backlog semantics.
function belongsToDay(task: TaskRow, day: string): boolean {
  if (task.recurs) return isRecurrenceDueOnDay(task.recurs, task.recurDay, day);
  if (task.plannedDate) return task.plannedDate === day;
  return task.status !== 'Done';
}

export function computeDayTasks(plan: PlanResponse, tasks: TaskRow[]): DayTask[] {
  const blockStartById = new Map(plan.blocks.map((b) => [b.taskId, b.start]));
  return tasks
    .filter((t) => belongsToDay(t, plan.day))
    .map((t) => ({
      ...t,
      effectiveTime: blockStartById.get(t.id) ?? t.scheduledTime ?? t.fixedTime ?? null,
    }));
}

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NoteForm } from './NoteForm';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

describe('NoteForm', () => {
  it('only enables Add once there is text', () => {
    render(<NoteForm />);
    const add = screen.getByRole('button', { name: 'Add' });
    expect(add).toBeDisabled();
    fireEvent.change(screen.getByLabelText('New note'), { target: { value: 'Hi' } });
    expect(add).toBeEnabled();
  });
});

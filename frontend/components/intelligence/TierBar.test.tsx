import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TierBar } from './TierBar';

describe('TierBar', () => {
  it('shows auto state with recommended tier', () => {
    render(<TierBar value="auto" onValueChange={() => {}} recommended="standard" />);
    const btn = screen.getByRole('button');
    expect(btn.textContent).toContain('智能选档');
    expect(btn.textContent).toContain('standard');
  });

  it('shows manual tier', () => {
    render(<TierBar value="deep" onValueChange={() => {}} />);
    const btn = screen.getByRole('button');
    expect(btn.textContent).toContain('手动');
    expect(btn.textContent).toContain('deep');
  });

  it('expands on click', () => {
    render(<TierBar value="auto" onValueChange={() => {}} recommended="standard" />);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByText('turbo')).toBeInTheDocument();
    expect(screen.getByText('deep')).toBeInTheDocument();
  });

  it('calls onValueChange when selecting tier', () => {
    const onChange = vi.fn();
    render(<TierBar value="auto" onValueChange={onChange} recommended="standard" />);
    fireEvent.click(screen.getByRole('button'));
    fireEvent.click(screen.getByText('deep'));
    expect(onChange).toHaveBeenCalledWith('deep');
  });
});

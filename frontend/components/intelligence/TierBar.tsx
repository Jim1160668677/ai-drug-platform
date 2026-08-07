'use client';

import { useState } from 'react';
import clsx from 'clsx';
import { Zap, ChevronDown, ChevronUp } from 'lucide-react';
import type { TierChoice } from '@/lib/api';

export type { TierChoice } from '@/lib/api';

interface TierBarProps {
  value: TierChoice;
  onValueChange: (tier: TierChoice) => void;
  recommended?: string | null;
  recommendedReason?: string | null;
  disabled?: boolean;
}

const TIER_META: Record<string, { label: string; desc: string; cost_hint: string; latency_hint: string }> = {
  turbo: { label: 'turbo', desc: '快筛', cost_hint: '约 $0.005', latency_hint: '~60s' },
  standard: { label: 'standard', desc: '标准', cost_hint: '约 $0.01', latency_hint: '~5min' },
  deep: { label: 'deep', desc: '深度', cost_hint: '约 $0.03', latency_hint: '~10min' },
};

export function TierBar({ value, onValueChange, recommended, recommendedReason, disabled }: TierBarProps) {
  const [expanded, setExpanded] = useState(false);
  const isAuto = value === 'auto';
  const displayTier = isAuto ? (recommended || 'standard') : value;
  const meta = TIER_META[displayTier] || TIER_META.standard;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 rounded-lg border border-gray-200 text-xs">
      <button
        onClick={() => !disabled && setExpanded(!expanded)}
        disabled={disabled}
        className="flex items-center gap-1.5 text-gray-600 hover:text-gray-800 disabled:opacity-50"
      >
        <Zap className={clsx('w-3.5 h-3.5', isAuto ? 'text-amber-500' : 'text-primary-500')} />
        <span>{isAuto ? '智能选档' : '手动'}: <strong>{displayTier}</strong></span>
        <span className="text-gray-400">{meta.cost_hint} · {meta.latency_hint}</span>
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>

      {expanded && (
        <div className="flex items-center gap-1">
          {(['turbo', 'standard', 'deep'] as TierChoice[]).map((tier) => (
            <button
              key={tier}
              onClick={() => { onValueChange(tier); setExpanded(false); }}
              disabled={disabled}
              className={clsx(
                'px-2 py-1 rounded text-xs font-medium transition-colors',
                value === tier
                  ? 'bg-primary-500 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200',
                disabled && 'opacity-50 cursor-not-allowed',
              )}
            >
              {tier}
            </button>
          ))}
          {isAuto && (
            <button
              onClick={() => { onValueChange('standard'); setExpanded(false); }}
              disabled={disabled}
              className="ml-1 text-[10px] text-gray-400 hover:text-gray-600"
            >
              恢复智能
            </button>
          )}
        </div>
      )}
    </div>
  );
}

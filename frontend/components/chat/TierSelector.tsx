'use client';

import { Zap } from 'lucide-react';
import type { TiersData } from '@/types/chat';

interface TierSelectorProps {
  tiers: TiersData | null;
  selectedTier: string;
  onTierSelect: (tier: string) => void;
}

export function TierSelector({ tiers, selectedTier, onTierSelect }: TierSelectorProps) {
  if (!tiers?.tiers) return null;

  return (
    <div className="grid grid-cols-2 gap-3">
      {tiers.tiers.map((t) => (
        <div
          key={t.name}
          className={`p-3 rounded-lg border cursor-pointer ${
            selectedTier === t.name
              ? 'border-primary-500 bg-primary-50'
              : 'border-gray-200 bg-white'
          }`}
          onClick={() => onTierSelect(t.name)}
        >
          <div className="flex items-center justify-between">
            <span className="font-medium text-sm">{t.label}</span>
            {selectedTier === t.name && <Zap className="w-4 h-4 text-primary-600" />}
          </div>
          <div className="text-xs text-gray-500 mt-1">{t.tech_stack}</div>
          <div className="text-xs text-gray-400 mt-1">
            &lt;${t.max_cost_usd} / &lt;{Math.floor(t.max_duration_sec / 60)}min
          </div>
        </div>
      ))}
    </div>
  );
}

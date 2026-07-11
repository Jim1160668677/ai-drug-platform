'use client';

import { Send, Sparkles } from 'lucide-react';
import Button from '@/components/ui/Button';

interface ChatInputProps {
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onAnalyze: () => void;
  isSending: boolean;
  isAnalyzing: boolean;
  canAnalyze: boolean;
}

export function ChatInput({
  input,
  onInputChange,
  onSend,
  onAnalyze,
  isSending,
  isAnalyzing,
  canAnalyze,
}: ChatInputProps) {
  return (
    <div className="border-t border-gray-200 pt-3">
      <div className="flex gap-2">
        <textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm resize-none"
          rows={2}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行..."
        />
        <div className="flex flex-col gap-1">
          <Button onClick={onSend} loading={isSending} disabled={!input.trim()} size="sm">
            <Send className="w-3 h-3" /> 发送
          </Button>
          <Button
            onClick={onAnalyze}
            loading={isAnalyzing}
            disabled={!input.trim() || !canAnalyze}
            size="sm"
            variant="secondary"
          >
            <Sparkles className="w-3 h-3" /> 深度分析
          </Button>
        </div>
      </div>
    </div>
  );
}

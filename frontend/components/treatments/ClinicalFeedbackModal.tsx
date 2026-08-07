'use client';

/**
 * ClinicalFeedbackModal — 临床反馈录入弹窗
 *
 * 最小可用实现：录入患者基本信息 + 疗效 + 不良反应 + 备注，提交后展示结果。
 * 设计来源：treatments/page.tsx 反馈流程
 */
import { X, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import Button from '@/components/ui/Button';

export interface FeedbackForm {
  patient_code: string;
  age: string;
  gender: string;
  dosage: string;
  duration_days: string;
  efficacy: string;
  adverse_reactions: string;
  biomarker_changes: string;
  notes: string;
}

interface ClinicalFeedbackModalProps {
  treatmentId: string;
  form: FeedbackForm;
  setForm: (f: FeedbackForm) => void;
  result: unknown;
  loading: boolean;
  onSubmit: () => void;
  onClose: () => void;
}

const EFFICACY_OPTIONS = [
  { value: 'complete', label: '完全缓解' },
  { value: 'partial', label: '部分缓解' },
  { value: 'stable', label: '稳定' },
  { value: 'progressive', label: '进展' },
];

const GENDER_OPTIONS = [
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
  { value: 'other', label: '其他' },
];

export function ClinicalFeedbackModal({
  treatmentId,
  form,
  setForm,
  result,
  loading,
  onSubmit,
  onClose,
}: ClinicalFeedbackModalProps) {
  const updateField = (field: keyof FeedbackForm, value: string) => {
    setForm({ ...form, [field]: value });
  };

  const inputClass =
    'w-full px-2.5 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-primary-500';

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
          <h3 className="text-base font-semibold text-gray-800">
            临床反馈录入
            <span className="ml-2 text-xs text-gray-400 font-mono">#{treatmentId.slice(0, 8)}</span>
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Field label="患者编码">
              <input
                type="text"
                value={form.patient_code}
                onChange={(e) => updateField('patient_code', e.target.value)}
                className={inputClass}
                placeholder="P-001"
              />
            </Field>
            <Field label="年龄">
              <input
                type="number"
                value={form.age}
                onChange={(e) => updateField('age', e.target.value)}
                className={inputClass}
                placeholder="45"
              />
            </Field>
            <Field label="性别">
              <select
                value={form.gender}
                onChange={(e) => updateField('gender', e.target.value)}
                className={inputClass}
              >
                <option value="">请选择</option>
                {GENDER_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="剂量">
              <input
                type="text"
                value={form.dosage}
                onChange={(e) => updateField('dosage', e.target.value)}
                className={inputClass}
                placeholder="10mg/day"
              />
            </Field>
            <Field label="持续天数">
              <input
                type="number"
                value={form.duration_days}
                onChange={(e) => updateField('duration_days', e.target.value)}
                className={inputClass}
                placeholder="30"
              />
            </Field>
          </div>

          <Field label="疗效评估">
            <select
              value={form.efficacy}
              onChange={(e) => updateField('efficacy', e.target.value)}
              className={inputClass}
            >
              {EFFICACY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </Field>

          <Field label="不良反应">
            <textarea
              value={form.adverse_reactions}
              onChange={(e) => updateField('adverse_reactions', e.target.value)}
              className={inputClass}
              rows={2}
              placeholder="恶心、乏力..."
            />
          </Field>

          <Field label="生物标志物变化">
            <textarea
              value={form.biomarker_changes}
              onChange={(e) => updateField('biomarker_changes', e.target.value)}
              className={inputClass}
              rows={2}
              placeholder="EGFR T790M 消失..."
            />
          </Field>

          <Field label="备注">
            <textarea
              value={form.notes}
              onChange={(e) => updateField('notes', e.target.value)}
              className={inputClass}
              rows={2}
            />
          </Field>

          {/* 结果展示 */}
          {result && (
            <div className="rounded-md border border-gray-200 bg-gray-50 p-3">
              <div className="flex items-center gap-1.5 text-xs font-medium text-green-700 mb-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>反馈已提交</span>
              </div>
              <pre className="text-[11px] text-gray-700 overflow-x-auto">
                {JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50 rounded-b-lg">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={loading}>
            取消
          </Button>
          <Button size="sm" onClick={onSubmit} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 提交中...
              </>
            ) : (
              <>
                <AlertCircle className="w-3.5 h-3.5" /> 提交反馈
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}

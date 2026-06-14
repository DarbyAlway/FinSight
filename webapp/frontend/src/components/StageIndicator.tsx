import type { StageInfo } from '../types';

const LABELS: Record<string, string> = {
  planning: 'Planning…',
  fetching: 'Fetching data…',
  writing: 'Writing answer…',
  verifying: 'Verifying numbers…',
  done: 'Finishing…',
};

export default function StageIndicator({ stage }: { stage: StageInfo | null }) {
  if (!stage) return null;
  const label = LABELS[stage.stage] ?? stage.stage;
  return (
    <div className="flex justify-start" role="status">
      <div className="flex items-center gap-3 rounded-2xl border border-green-500/40 bg-green-500/10 px-4 py-3 text-green-100 shadow-sm">
        <span
          className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-green-400 border-t-transparent"
          aria-hidden="true"
        />
        <span className="text-sm font-medium">
          {label}
          {stage.detail ? ` (${stage.detail})` : ''}
        </span>
      </div>
    </div>
  );
}

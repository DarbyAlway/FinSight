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
    <div className="flex items-center gap-2 px-4 py-2 text-sm text-gray-500" role="status">
      <span className="animate-pulse">●</span>
      <span>
        {label}
        {stage.detail ? ` (${stage.detail})` : ''}
      </span>
    </div>
  );
}

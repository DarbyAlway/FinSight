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
    <div
      className="mx-auto flex w-full max-w-3xl items-center gap-2 px-4 py-2 text-sm text-neutral-400"
      role="status"
    >
      <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-400" aria-hidden="true" />
      <span>
        {label}
        {stage.detail ? ` (${stage.detail})` : ''}
      </span>
    </div>
  );
}

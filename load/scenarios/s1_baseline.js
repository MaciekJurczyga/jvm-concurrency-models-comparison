// S1: baseline load in steps until clear degradation -> saturation point (plan section 5).
// Env: ENDPOINT, START_RATE, STEP_RATE, MAX_RATE, STEP_DURATION_S, PRE_VUS, MAX_VUS.
import exec from 'k6/execution';
import { commonOptions, GRACEFUL_STOP, hit, num } from '../lib/common.js';

export { handleSummary } from '../lib/common.js';

const START_RATE = num('START_RATE');
const STEP_RATE = num('STEP_RATE');
const MAX_RATE = num('MAX_RATE');
const STEP_DURATION_S = num('STEP_DURATION_S');

const levels = [];
for (let r = START_RATE; r <= MAX_RATE; r += STEP_RATE) {
  levels.push(r);
}

// Steps, not ramps: each level is reached instantly (0 s stage) and held, so every request belongs to exactly one rate level.
const stages = levels.flatMap((r) => [
  { duration: '0s', target: r },
  { duration: `${STEP_DURATION_S}s`, target: r },
]);

export const options = {
  ...commonOptions,
  scenarios: {
    baseline: {
      // Open model: arrivals do not slow down when the server does (coordinated omission, plan section 5).
      executor: 'ramping-arrival-rate',
      startRate: START_RATE,
      timeUnit: '1s',
      stages,
      preAllocatedVUs: num('PRE_VUS', 50),
      maxVUs: num('MAX_VUS'),
      gracefulStop: GRACEFUL_STOP,
      tags: { test: 's1' },
    },
  },
};

export default function () {
  const elapsedS = (Date.now() - exec.scenario.startTime) / 1000;
  const i = Math.min(Math.floor(elapsedS / STEP_DURATION_S), levels.length - 1);
  hit({ stage: String(i + 1), rate: String(levels[i]) });
}

// JIT warm-up before each measured run, discarded from analysis (plan section 6). Also a quick manual smoke test.
// Env: ENDPOINT, RATE, DURATION_S.
import { commonOptions, GRACEFUL_STOP, hit, num } from '../lib/common.js';

export { handleSummary } from '../lib/common.js';

const RATE = num('RATE', 20);

export const options = {
  ...commonOptions,
  scenarios: {
    warmup: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: `${num('DURATION_S', 30)}s`,
      preAllocatedVUs: Math.max(10, Math.ceil(RATE / 5)),
      maxVUs: num('MAX_VUS', Math.max(100, RATE * 2)),
      gracefulStop: GRACEFUL_STOP,
      tags: { test: 'warmup' },
    },
  },
};

export default function () {
  hit({});
}

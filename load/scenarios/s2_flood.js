// S2: HTTP flood in phases: normal -> flood -> normal; time to failure and time to recovery (plan section 5, Huang et al.).
// Env: ENDPOINT, NORMAL_RATE, FLOOD_RATE, BEFORE_S, FLOOD_S, AFTER_S, PRE_VUS, MAX_VUS (flood phase), NORMAL_MAX_VUS.
import { commonOptions, GRACEFUL_STOP, hit, num } from '../lib/common.js';

export { handleSummary } from '../lib/common.js';

const NORMAL_RATE = num('NORMAL_RATE');
const FLOOD_RATE = num('FLOOD_RATE');
const BEFORE_S = num('BEFORE_S');
const FLOOD_S = num('FLOOD_S');
const AFTER_S = num('AFTER_S');
const PRE_VUS = num('PRE_VUS', 50);
const MAX_VUS = num('MAX_VUS');
// The "after" phase must keep its arrival rate even while flood requests are still timing out,
// so it gets the same VU budget as the flood by default.
const NORMAL_MAX_VUS = num('NORMAL_MAX_VUS', MAX_VUS);

// Open model in every phase (plan section 5); one scenario per phase so each request carries its phase tag.
function phase(name, rate, startS, durationS, maxVUs) {
  return {
    executor: 'constant-arrival-rate',
    rate,
    timeUnit: '1s',
    startTime: `${startS}s`,
    duration: `${durationS}s`,
    preAllocatedVUs: Math.min(PRE_VUS, maxVUs),
    maxVUs,
    gracefulStop: GRACEFUL_STOP,
    tags: { test: 's2', phase: name },
  };
}

export const options = {
  ...commonOptions,
  scenarios: {
    before: phase('before', NORMAL_RATE, 0, BEFORE_S, NORMAL_MAX_VUS),
    flood: phase('flood', FLOOD_RATE, BEFORE_S, FLOOD_S, MAX_VUS),
    after: phase('after', NORMAL_RATE, BEFORE_S + FLOOD_S, AFTER_S, NORMAL_MAX_VUS),
  },
};

export default function () {
  hit({});
}

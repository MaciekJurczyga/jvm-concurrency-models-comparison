// Infrastructure check (E4), not a measurement scenario: low constant rate on one endpoint.
//   docker compose -f infra/docker-compose.yml run --rm k6 run -o experimental-prometheus-rw /load/scenarios/smoke.js
import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://sut:8080';
const ENDPOINT = __ENV.ENDPOINT || '/io';

export const options = {
  scenarios: {
    smoke: {
      // Open model, as in all scenarios (plan section 5).
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20),
      timeUnit: '1s',
      duration: __ENV.DURATION || '30s',
      preAllocatedVUs: 10,
      maxVUs: 100,
    },
  },
  tags: { endpoint: ENDPOINT },
};

export default function () {
  const res = http.get(`${BASE_URL}${ENDPOINT}`, { timeout: '10s' });
  check(res, { 'status 200': (r) => r.status === 200 });
}

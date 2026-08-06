import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 }, // Ramp up to 50 users
    { duration: '1m', target: 50 },  // Stay at 50 users
    { duration: '30s', target: 0 },  // Scale down to 0
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'], // 95% of requests must complete under 3s (Target)
  },
};

export default function () {
  const url = 'http://localhost:8000/api/chat';
  
  const payload = JSON.stringify({
    messages: [
      { role: 'user', content: 'What formal shoes do you have?' }
    ],
    customer_id: 'C001',
    cart_id: 'cart_C001',
    current_order_id: '',
    active_node: 'general',
    intent: 'general'
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(url, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has assistant response': (r) => r.json().messages.slice(-1)[0].role === 'assistant',
  });

  sleep(1);
}

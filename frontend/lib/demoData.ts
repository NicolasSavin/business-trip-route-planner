import type { RouteSearchResponse } from './types';

export const demoResponse: RouteSearchResponse = {
  routes: [
    {
      id: 'demo-direct', origin: 'Москва', destination: 'Екатеринбург', transfer_city: null, transfer_duration_minutes: null, total_duration_minutes: 840, transfers_count: 0, is_available_for_group: true,
      segments: [{ id: 'tr-msk-ekb-001', origin: 'Москва', destination: 'Екатеринбург', transport_type: 'train', number: 'Поезд 016М', departure_time: '2026-08-10T09:00:00', arrival_time: '2026-08-10T23:00:00', available_seats: 8 }],
    },
    {
      id: 'demo-kazan', origin: 'Москва', destination: 'Екатеринбург', transfer_city: 'Казань', transfer_duration_minutes: 120, total_duration_minutes: 930, transfers_count: 1, is_available_for_group: true,
      segments: [
        { id: 'tr-msk-kzn-001', origin: 'Москва', destination: 'Казань', transport_type: 'train', number: 'Поезд 024М', departure_time: '2026-08-10T08:00:00', arrival_time: '2026-08-10T15:00:00', available_seats: 12 },
        { id: 'bus-kzn-ekb-001', origin: 'Казань', destination: 'Екатеринбург', transport_type: 'bus', number: 'Автобус К-204', departure_time: '2026-08-10T17:00:00', arrival_time: '2026-08-10T23:30:00', available_seats: 10 },
      ],
    },
  ],
};

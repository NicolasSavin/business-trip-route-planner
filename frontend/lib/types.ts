export type TransportType = 'train' | 'bus';
export type RouteSegment = { id:string; origin:string; destination:string; transport_type:TransportType; number:string; departure_time:string; arrival_time:string; available_seats:number };
export type RouteOption = { id:string; origin:string; destination:string; segments:RouteSegment[]; transfer_city:string|null; transfer_duration_minutes:number|null; total_duration_minutes:number; transfers_count:number; is_available_for_group:boolean };
export type RouteSearchResponse = { routes: RouteOption[] };

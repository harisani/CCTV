# CCTV People Flow Dashboard

React + Vite + Material UI dashboard for the CCTV people-flow API.

## Run locally

```bash
cp .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`. The default API address is
`http://localhost:8000/api/v1`; override it through `VITE_API_BASE_URL`.

## Realtime WebSocket message contract

The dashboard connects to `/api/v1/ws/dashboard?token=<jwt>` and accepts:

```json
{
  "type": "frame",
  "camera_id": "front-door",
  "image": "base64-jpeg",
  "width": 1280,
  "height": 720,
  "tracks": [{"tracking_id": 7, "bbox": [100, 80, 260, 420], "direction": "down"}]
}
```

`event` messages add a row to the event history, while `occupancy` messages
contain `{ "type": "occupancy", "count": 3 }`.

The camera/pipeline coordinator should call `dashboard_hub.publish_frame()`,
`dashboard_hub.publish_event()`, and `dashboard_hub.publish_occupancy()` after
processing its corresponding realtime data.

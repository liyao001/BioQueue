ui2-frontend

react + vite (typescript) frontend for the ui2 apis.

dev

- ensure django backend runs on http://localhost:8000
- then in this folder:

```
npm install
npm run dev
```

open http://localhost:5173

features

- job search with `/api/ui/jobs/search/`
- dag viewer with `/api/ui/jobs/dag/`

vite dev proxy forwards `/api` to `localhost:8000`.



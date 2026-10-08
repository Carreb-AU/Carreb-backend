# GVG Deployment Runbook (main branch)

> Copy-paste commands for the Ubuntu server. This runbook uses our full GVG model + import command, with the trigram search index.

## 1. Check what branch you are on

```bash
cd ~/Carreb-backend
git branch --show-current
```

You should see `main`. If not, switch:

```bash
git checkout main
git pull origin main
```

## 2. Make sure PostgreSQL can use trigrams

The GVG search needs the `pg_trgm` extension. Inside the running `db` container:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

If this fails with permission errors, the migration will also fail. The default `postgres` user in the Docker image can create extensions.

## 3. Build and start containers

```bash
cd ~/Carreb-backend
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

Wait until all containers are healthy:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

You should see `web`, `celery`, `celery-beat`, `db`, `redis`, and `nginx` all `Up`.

## 4. Run migrations

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py migrate
```

This applies migration `0007_greenvehicleguiderecord_search_text`, which:
- Enables the `pg_trgm` extension
- Adds the `search_text` column
- Populates `search_text` for existing GVG records
- Creates the GIN trigram index

## 5. Import the GVG data

You need three files in `~/Carreb-backend/`:

- `Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx`
- `docs/GVG-Vehicles-2004-2025.xlsx`
- `docs/FuelConsumptionGuide1986-2003.csv`

Run the import command:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py import_gvg_data all --clear \
  --workbook "Carreb Calc Workbook and Data - v6.4 Launch 10-Jul-26.xlsx" \
  --gvg-xlsx docs/GVG-Vehicles-2004-2025.xlsx \
  --old-csv docs/FuelConsumptionGuide1986-2003.csv
```

This imports category cost defaults and both GVG datasets in one pass. `search_text` is populated during import.

## 6. Test the search endpoint

From the server or any machine:

```bash
curl -X POST https://api.carreb.com.au/api/my-garage/current-vehicle/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "toyota camry 1990"}'
```

You should get JSON results. If you get `502`, wait 30 seconds and try again — the web container may still be starting.

Try a fuzzy/typo query too:

```bash
curl -X POST https://api.carreb.com.au/api/my-garage/current-vehicle/search/ \
  -H "Content-Type: application/json" \
  -d '{"query": "corlla 2010"}'
```

## 7. Test setting a GVG current vehicle

Pick a `green_vehicle_guide_record_id` UUID from the search response, then:

```bash
curl -X POST https://api.carreb.com.au/api/my-garage/current-vehicle/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your_token>" \
  -d '{"green_vehicle_guide_record_id": "<uuid_from_search>", "state": "NSW"}'
```

Replace `<your_token>` with a logged-in user's JWT.

## 8. What to do if the search returns 404 or 502

| Symptom | Cause | Fix |
|---------|-------|-----|
| `POST /api/my-garage/current-vehicle/search/` returns 502 | Web container restarting | Wait 30s, check `docker compose ... ps` |
| `POST /api/my-garage/current-vehicle/search/` returns 404 | Wrong URL | Use the exact path above with trailing slash |
| `GET /api/vehicles/<id>/` returns 404 after selecting a GVG result | Frontend is using the wrong endpoint | See `docs/frontend-integration-current-vehicle-search.md` |
| Import fails with `pg_trgm` | Extension not enabled | Run step 2 first, then migrate again |
| "No matching vehicles" after Continue | Frontend is not sending `green_vehicle_guide_record_id` | See frontend integration guide |

## 9. Why the IP changed

When you ran `docker compose up -d --build`, Docker recreated the `web` container. The old container's IP was removed, and Nginx upstream still pointed to the old IP for a few seconds. That caused any brief `502` errors. Once the new container was healthy and Nginx re-resolved its hostname, traffic worked again. The IP itself is not important — Docker DNS resolves `web` to the new container.

## 10. Useful log commands

```bash
# All containers
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail 100

# Just the web container
docker compose --env-file .env.prod -f docker-compose.prod.yml logs web --tail 100

# Just the nginx container
docker compose --env-file .env.prod -f docker-compose.prod.yml logs nginx --tail 100
```

## 11. Re-populating search_text manually (if needed)

If you ever need to rebuild the `search_text` column (for example, after a data fix):

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py shell <<'PY'
from apps.vehicles.models import GreenVehicleGuideRecord
for record in GreenVehicleGuideRecord.objects.all().iterator():
    record.search_text = ' '.join(p for p in [str(record.year), record.make, record.model, record.variant] if p).lower()
    record.save(update_fields=['search_text'])
print('Done')
PY
```

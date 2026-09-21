#!/usr/bin/env bash
# Backfill RAT_ECON_INDEX with IPC_CL from 2013-01 through 2025-07
# (151 months across 13 yearly chunks).
#
# History (see pf-rates/docs/api.md#refresh-economic-indices):
# - 2010-01 through 2012-12 are NOT available from any configured
#   provider (confirmed via 4 rounds of manual probing) -- do not
#   retry those months, they will always fail the same way.
# - 2013-01 onward is confirmed available. 2025-08+ was already
#   stored before this script existed.
#
# Chunked by year (not one giant request) on purpose: the refresh
# endpoint is all-or-nothing PER REQUEST -- one bad month discards
# the whole request, not just that month. Chunking by year limits
# the blast radius to at most 12 months, and this script keeps going
# even if one year's chunk fails (no `set -e` around the curl calls).
#
# Usage:
#   export PF_RATES_API_KEY="..."
#   export PF_RATES_BASE_URL="https://..."  # optional
#   ./backfill_ipc_cl_2013_2025.sh

set -uo pipefail  # deliberately no -e: one failed year must not stop the rest

: "${PF_RATES_API_KEY:?Set PF_RATES_API_KEY before running this script}"
BASE_URL="${PF_RATES_BASE_URL:-https://pf-rates-646185261155.us-central1.run.app}"

failed_years=()

echo "=== 2013 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2013,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2013"); fi
echo ""

echo "=== 2014 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2014,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2014"); fi
echo ""

echo "=== 2015 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2015,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2015"); fi
echo ""

echo "=== 2016 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2016,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2016"); fi
echo ""

echo "=== 2017 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2017,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2017"); fi
echo ""

echo "=== 2018 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2018,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2018"); fi
echo ""

echo "=== 2019 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2019,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2019"); fi
echo ""

echo "=== 2020 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2020,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2020"); fi
echo ""

echo "=== 2021 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2021,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2021"); fi
echo ""

echo "=== 2022 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2022,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2022"); fi
echo ""

echo "=== 2023 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2023,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2023"); fi
echo ""

echo "=== 2024 (12 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 7
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 8
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 9
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 10
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 11
    },
    {
      "code": "IPC_CL",
      "period_year": 2024,
      "period_month": 12
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2024"); fi
echo ""

echo "=== 2025 (7 months) ==="
response=$(curl -s -X POST -H "X-API-Key: ${PF_RATES_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
  "fetch_economic_indices": [
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 1
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 2
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 3
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 4
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 5
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 6
    },
    {
      "code": "IPC_CL",
      "period_year": 2025,
      "period_month": 7
    }
  ]
}' \
  "${BASE_URL}/economic-indices/refresh")
echo "$response"
if [[ "$response" == *"detail"* ]]; then failed_years+=("2025"); fi
echo ""

echo "=== Done. ==="
if [ "${#failed_years[@]}" -gt 0 ]; then
  echo "Years that failed (send these back to code-puppy to investigate): ${failed_years[*]}"
else
  echo "All years succeeded."
fi

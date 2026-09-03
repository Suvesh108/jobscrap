import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
import scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ponytail: minimal stdlib asyncio daemon replaces heavy Celery/APScheduler dependencies
async def scrape_loop(query: str, count: int, interval_hours: float):
    interval_sec = max(60.0, interval_hours * 3600.0)
    while True:
        logging.info(f"Starting scheduled scrape run (query='{query}', count={count})...")
        try:
            scraper.run_pipeline(source="all", query=query, count=count)
        except Exception as e:
            logging.error(f"Error during scheduled scrape: {e}")
        logging.info(f"Scrape run finished. Sleeping for {interval_hours} hours...")
        await asyncio.sleep(interval_sec)

async def validation_loop(interval_hours: float, stale_hours: int):
    interval_sec = max(60.0, interval_hours * 3600.0)
    while True:
        logging.info(f"Starting scheduled link validation pass (stale_hours={stale_hours})...")
        try:
            await scraper.run_link_validation(stale_hours=stale_hours)
        except Exception as e:
            logging.error(f"Error during scheduled validation: {e}")
        logging.info(f"Validation finished. Sleeping for {interval_hours} hours...")
        await asyncio.sleep(interval_sec)

async def main(query: str, count: int, scrape_hours: float, validate_hours: float, stale_hours: int):
    logging.info(f"Starting JobScrap Autonomous Daemon: Scrape every {scrape_hours}h | Validate every {validate_hours}h")
    await asyncio.gather(
        scrape_loop(query, count, scrape_hours),
        validation_loop(validate_hours, stale_hours)
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JobScrap Autonomous Scheduler Daemon")
    parser.add_argument("--query", default="developer", help="Job query keyword")
    parser.add_argument("--count", type=int, default=10, help="Jobs per board per run")
    parser.add_argument("--scrape-hours", type=float, default=12.0, help="Scrape interval in hours")
    parser.add_argument("--validate-hours", type=float, default=4.0, help="Link check interval in hours")
    parser.add_argument("--stale-hours", type=int, default=6, help="Stale threshold in hours")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.query, args.count, args.scrape_hours, args.validate_hours, args.stale_hours))
    except (KeyboardInterrupt, SystemExit):
        logging.info("Scheduler daemon stopped.")

#!/usr/bin/env python3
"""
download_euroc.py - Single-stream resumable range downloader for EuRoC datasets.

Supports:
  - MH_01_easy (from research-collection.ethz.ch machine_hall.zip)
  - V1_01_easy (from vicon_room1.zip)
"""

import os
import sys
import time
import zlib
import zipfile
import argparse
import requests

CONFIGS = {
    "MH_01_easy": {
        "url": "https://www.research-collection.ethz.ch/server/api/core/bitstreams/7b2419c1-62b5-4714-b7f8-485e5fe3e5fe/content",
        "data_start": 8572438037,
        "data_end": 10143569891,
        "total_compressed": 1571131855,
        "raw_name": "MH_01_easy.raw",
        "zip_name": "MH_01_easy.zip",
    },
    "V1_01_easy": {
        "url": "https://huggingface.co/datasets/GlowBond/EuRoC_MAV_Dataset/resolve/main/vicon_room1.zip",
        "data_start": 1540401978,
        "data_end": 2689937329,
        "total_compressed": 1149535352,
        "raw_name": "V1_01_easy.raw",
        "zip_name": "V1_01_easy.zip",
    }
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 "
    "(EuRoC-Dataset-Downloader/1.0; Research-Tool)"
)

CHUNK_SIZE = 1024 * 1024  # 1 MB

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "data", "_download")


def log_message(msg, log_path):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except OSError:
        pass


def parse_retry_after(header_val):
    if not header_val:
        return None
    try:
        return max(1, int(header_val))
    except ValueError:
        return 60


def unpack_raw_to_zip(raw_path, zip_path, log_path):
    log_message(f"Decompressing {raw_path} into {zip_path} via raw Deflate...", log_path)
    d = zlib.decompressobj(-15)
    with open(raw_path, "rb") as fin, open(zip_path, "wb") as fout:
        while True:
            chunk = fin.read(CHUNK_SIZE * 4)
            if not chunk:
                break
            fout.write(d.decompress(chunk))
        fout.write(d.flush())
    log_message(f"Decompression finished: {os.path.getsize(zip_path):,} bytes written.", log_path)


def extract_needed_files(zip_path, target_dir, log_path):
    log_message(f"Extracting IMU and groundtruth from {zip_path} into {target_dir}...", log_path)
    os.makedirs(target_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if "imu0/data.csv" in member or "groundtruth" in member.lower() or "state_groundtruth_estimate0/data.csv" in member:
                zf.extract(member, target_dir)
                log_message(f"  Extracted: {member}", log_path)


def download_sequence(seq_name):
    cfg = CONFIGS[seq_name]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    raw_path = os.path.join(DOWNLOAD_DIR, cfg["raw_name"])
    zip_path = os.path.join(DOWNLOAD_DIR, cfg["zip_name"])
    log_path = os.path.join(DOWNLOAD_DIR, f"progress_{seq_name}.log")

    log_message(f"Starting EuRoC {seq_name} single-stream range downloader.", log_path)
    log_message(f"Source URL: {cfg['url']}", log_path)
    log_message(f"Target byte range: {cfg['data_start']}..{cfg['data_end']} ({cfg['total_compressed']:,} bytes)", log_path)
    log_message(f"Output raw file: {raw_path}", log_path)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    backoff = 10
    max_backoff = 300

    while True:
        current_size = os.path.getsize(raw_path) if os.path.exists(raw_path) else 0
        if current_size >= cfg["total_compressed"]:
            log_message(f"Raw download complete: {current_size:,} bytes on disk.", log_path)
            break

        req_start = cfg["data_start"] + current_size
        req_end = cfg["data_end"]
        range_header = f"bytes={req_start}-{req_end}"
        log_message(
            f"Initiating stream: Range {range_header} "
            f"({current_size:,}/{cfg['total_compressed']:,} bytes, {current_size/cfg['total_compressed']*100:.2f}%)",
            log_path
        )

        try:
            resp = session.get(cfg["url"], headers={"Range": range_header}, stream=True, timeout=60)

            if resp.status_code == 429:
                wait_time = parse_retry_after(resp.headers.get("Retry-After")) or backoff
                log_message(f"HTTP 429 Rate limited. Waiting {wait_time}s...", log_path)
                time.sleep(wait_time)
                backoff = min(backoff * 2, max_backoff)
                continue

            if resp.status_code >= 500:
                log_message(f"HTTP {resp.status_code} server error. Waiting {backoff}s...", log_path)
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            if resp.status_code not in (200, 206):
                log_message(f"Unexpected HTTP {resp.status_code}. Waiting {backoff}s...", log_path)
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            backoff = 10
            log_message(f"Connected (HTTP {resp.status_code}). Streaming in 1 MB chunks...", log_path)

            last_log_time = time.time()
            bytes_since_log = 0

            with open(raw_path, "ab") as f_out:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    f_out.write(chunk)
                    f_out.flush()
                    current_size += len(chunk)
                    bytes_since_log += len(chunk)

                    now = time.time()
                    elapsed = now - last_log_time
                    if elapsed >= 15:
                        speed = (bytes_since_log / (1024 * 1024)) / elapsed
                        pct = (current_size / cfg["total_compressed"]) * 100
                        rem_bytes = cfg["total_compressed"] - current_size
                        eta_sec = rem_bytes / (speed * 1024 * 1024) if speed > 0 else 0
                        eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
                        log_message(
                            f"Progress: {current_size:,}/{cfg['total_compressed']:,} bytes ({pct:.2f}%) | "
                            f"Speed: {speed:.2f} MB/s | ETA: {eta_str}",
                            log_path
                        )
                        last_log_time = now
                        bytes_since_log = 0

            if current_size >= cfg["total_compressed"]:
                log_message(f"Stream finished. Total downloaded: {current_size:,} bytes.", log_path)
                break
            else:
                log_message(f"Stream ended early at {current_size:,} bytes. Reconnecting...", log_path)
                time.sleep(2)

        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            log_message(f"Network error: {e}. Retrying in {backoff}s...", log_path)
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    final_size = os.path.getsize(raw_path) if os.path.exists(raw_path) else 0
    if final_size >= cfg["total_compressed"]:
        log_message(f"Download complete ({final_size:,} bytes).", log_path)
        unpack_raw_to_zip(raw_path, zip_path, log_path)
        extract_needed_files(zip_path, os.path.join(BASE_DIR, "data", seq_name), log_path)
        log_message(f"All processing complete for {seq_name}.", log_path)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="EuRoC Dataset Resumable Downloader")
    parser.add_argument("--seq", choices=["MH_01_easy", "V1_01_easy"], default="V1_01_easy", help="Dataset sequence to download")
    args = parser.parse_args()

    success = download_sequence(args.seq)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

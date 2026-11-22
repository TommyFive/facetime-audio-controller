#!/usr/bin/env python3
"""Read-only CLI for FaceTime usage. No MCP endpoint and no speech transcripts."""
import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import facetime_usage as usage


def date_arg(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize owner-only FaceTime usage metadata")
    parser.add_argument("--since", type=date_arg, help="First UTC date inclusive (YYYY-MM-DD)")
    parser.add_argument("--until", type=date_arg, help="Last UTC date inclusive (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Machine-readable, aggregated JSON only")
    args = parser.parse_args(argv)
    if args.since and args.until and args.since > args.until:
        parser.error("--since must be on or before --until")
    try:
        events = usage.read_events()
        report = usage.summarize(events, args.since, args.until)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("USAGE_READ_ERROR: " + type(exc).__name__, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print("FaceTime Controller usage (UTC; captured since journal deployment)")
    print("MiniMax HTTP attempts:          ", report["minimax_requests"])
    print("MiniMax generated responses:    ", report["minimax_generated"])
    print("MiniMax input characters:       ", report["minimax_input_characters"])
    print("MiniMax known usage characters: ", report["minimax_usage_characters_known"])
    print("MiniMax attempts without usage: ", report["minimax_usage_unknown"])
    def model_row(label, stats):
        print("  " + label)
        print(f'    Requests: {stats["attempts"]}; successful API responses: {stats["generated_responses"]}')
        print(f'    Submitted characters: {stats["submitted_characters"]}; provider usage characters: {stats["reported_usage_characters"]}; unknown usage: {stats["unknown_usage_attempts"]}')
        print(f'    Rendered files: {stats["rendered_count"]}; rendered characters: {stats["rendered_characters"]}; audio: {stats["rendered_audio_seconds"]:.3f} s ({stats["rendered_audio_seconds"]/3600:.4f} hours)')
    print("\nMiniMax TOTAL (HD + Turbo, excluding macOS fallback):")
    model_row("All MiniMax models", report["minimax_total"])
    print("\nMiniMax BY MODEL:")
    for model in usage.MINIMAX_MODELS:
        model_row(model, report["minimax_by_model"][model])
    print("Completed TTS renderings:       ", report["rendered_count"])
    print("Rendered input characters:     ", report["rendered_characters"])
    print("Generated audio:               ", f'{report["rendered_audio_seconds"]/3600:.3f} hours')
    print("Call attempts:                 ", report["calls"])
    print("Call connected / completed:    ", f'{report["calls_connected"]} / {report["calls_completed"]}')
    print("Dialed but not connected:      ", report["calls_not_connected"])
    print("Call playback complete:        ", report["calls_playback_completed"])
    print("Total controller call runtime: ", f'{report["call_elapsed_seconds"]/3600:.3f} hours')
    print("\nTTS renderings by endpoint / model / origin:")
    for key, item in sorted(report["by_render"].items()):
        print(f'  {key}: {item["count"]} renders, {item["characters"]} chars, {item["audio_seconds"]/3600:.3f} hours')
    print("\nMiniMax attempts by endpoint / model / result:")
    for key, item in sorted(report["by_api"].items()):
        print(f'  {key}: {item["count"]} attempts, {item["characters"]} submitted chars')
    print("\nCall outcomes:")
    for key, amount in sorted(report["by_outcome"].items()):
        print(f"  {key}: {amount}")
    print("\nNote: Usage characters are provider-reported only when available; not a billing statement.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

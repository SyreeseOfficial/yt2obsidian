# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(Terminal app, Linux/Wayland. Closest schema value is `web`; no mobile or native-OS design language applies.)

## Users

One person, the author: an Obsidian Sync user on Arch/Omarchy (Hyprland). Pastes YouTube links many times a day, often in batches, from a terminal or a hotkey.

## Product Purpose

Turn a YouTube link into a plain-text transcript note in an Obsidian vault. Free, no AI. Success: paste, see it filed, move on.

## Positioning

A personal tool with a personality. The terminal UI should feel like a small companion, not a log.

## Operating Context

Runs in a terminal (`yt`) or from a hotkey with no terminal (clipboard in, toast out). The save pipeline lives in `yt2obsidian.py` and stays the single source of behavior; scripted `yt <url>`, `--retry`, exit codes and `run.log` must not change.

## Capabilities and Constraints

- Interactive surface is now a full-screen Textual TUI that replaces the line prompt. Dependency on `textual` is accepted.
- Needs: live per-link progress, batch and retry clarity, visible commands, a settings screen.
- Settings keys and `config.toml` format are unchanged.

## Brand Commitments

Playful, mascot-level personality (confirmed by the user). The mascot must never slow the 50th paste of the day.

## Product Principles

1. Pasting is the whole job; everything else is one key away and always shown.
2. Every link gets a visible row and a plain-language outcome.
3. Personality lives in the mascot and copy, never in extra steps.
4. Failures name the cause and the recovery.

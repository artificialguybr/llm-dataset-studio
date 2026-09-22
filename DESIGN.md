---
name: LLM Dataset Studio
version: alpha
description: "Clean, dark, data-first UI for LLM text dataset curation — corpus, SFT, DPO, reasoning traces. No images."
colors:
  primary: "#0F172A"
  secondary: "#334155"
  tertiary: "#38BDF8"
  neutral: "#94A3B8"
  surface: "#1E293B"
  on-surface: "#F8FAFC"
  success: "#10B981"
  warn: "#F59E0B"
  critical: "#EF4444"
  clean-paper: "#F4F6F9"
typography:
  h1:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: -0.02em
  h2:
    fontFamily: "Inter"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.3
  body-md:
    fontFamily: "Inter"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  label-md:
    fontFamily: "Inter"
    fontSize: 13px
    fontWeight: 500
    letterSpacing: 0.01em
rounded:
  sm: 6px
  md: 10px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
---

## Overview
The Studio is local-first, text-only, dataset-curation software. Dark slate base, cool blue interactive accent, clean paper-style data cards. Every decision is reversible: keep / review / quarantine / reject / restore / chosen / rejected.

The user is a data engineer / ML researcher who curates LLM training and evaluation sets: corpus for pretraining, instruction-following pairs (SFT), preference pairs (DPO), agent traces, reasoning traces, benchmark decontamination, and versioned splits. No model training happens inside the Studio.

## Colors
- **Primary (#0F172A):** Deep slate — background, headers.
- **Surface (#1E293B):** Card background, panels.
- **On-surface (#F8FAFC):** Main text.
- **Tertiary (#38BDF8):** Interactive accent — links, active tabs, progress, kept-state.
- **Success (#10B981):** Keep / chosen / verified.
- **Warn (#F59E0B):** Review / chosen but flagged.
- **Critical (#EF4444):** Reject / rejected / blocked.
- **Clean-paper (#F4F6F9):** Light-mode cards, export preview.

## Typography
Monolinear sans-serif only. Monospace reserved for token counts, JSON previews, IDs, and raw text samples. Headline weight always 600; body 400; never italic for labels.

## Layout
- **Dashboard (top):** Stats row (total texts, tokens, conversation turns, duplicates, quality issues) → cards, no charts.
- **Navigation (left rail):** Dataset list, Import, Catalog, Quality, Review, Duplicates, Decontamination, Versions, Export, Settings.
- **Content (main):** Large scrollable list/table view per dataset; row = text / conversation / pair / trace.
- **Side detail (right):** When a row is selected, a detail panel shows source, provenance, statistics, quality flags, review comments, history.
- **Footer: persistent status** (last sync, active job, dataset version).

No hero image. No visual effects. No animations beyond a subtle 120ms opacity fade on panel open/close.

## Components
- **DatasetRow:** id, title, format (corpus / sft / dpo / trace), token count, status, license.
- **StatusBadge:** keep / review / quarantine / reject / restore / chosen / rejected (small pill, color-coded, always visible).
- **TextPreview:** First 240 chars of text or conversation; click to expand full JSONL/parquet preview.
- **StatChip:** token count / turn count / character count (small, neutral, monospace).
- **ReviewPanel:** Human comment input + decision dropdown + adjudication checkbox. Comments are always saved; final decision is reversible.
- **QualityFlagsRow:** one chip per quality issue (language, repetition, size, spam, code, secrets, toxicity, benchmark overlap) — not a score, a set of flags.
- **SplitRecipeCard:** train/eval split config (ratio, seed, stratify by field) with leakage guard.
- **VersionDiffRow:** added / removed / modified counts; rollback button always visible.
- **ExportButton:** JSONL / Parquet / HF dataset / manifest / audit report; always produces a single file + checksum JSON.

## Do's and Don'ts
- **DO** keep original files untouched; write only to `.hermes/` data directory.
- **DO** make every destructive action explainable (reason field, reviewer field, timestamp) and reversible.
- **DO** use text-first previews; never display an image thumbnail.
- **DO NOT** train or fine-tune models in this interface.
- **DO NOT** hide destructive actions (rejection, split creation, version rollback) inside opaque bulk jobs.
- **DO NOT** allow delete without an audit record.

## Dataset Domains (text / LLM, replacing image-specific modules)
- **Corpus:** Raw text for pretraining (JSONL, TXT, folder, Hugging Face dataset manifest).
- **SFT:** Instruction / response / chosen pairs.
- **DPO:** Preference pairs (chosen / rejected / prompt).
- **Agent traces:** Tool calls, observations, agent reasoning.
- **Reasoning traces:** Chain-of-thought, step-level solutions, verifiers.
- **Benchmark decontamination:** Overlap detection against MMLU, HumanEval, GSM8K, etc.
- **Synthetic / derived:** Generated review comments, adjudication, sampling strategies.

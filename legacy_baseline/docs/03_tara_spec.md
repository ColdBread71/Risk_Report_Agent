# TARA Analysis Spec

## Purpose

This document defines the input/output contract for the TARA analysis stage.

## Input Contract

The analysis stage must accept a strictly validated `ProductProfile` object.

## Output Contract

The analysis stage must return a strictly validated `TaraReport` object.

## Output Content

The report should contain:

- risk scenario
- affected function or context element
- threat category
- risk description
- scoring result
- regulation reference
- evidence reference
- confidence or certainty note
- unresolved questions if any

## Output Rules

- Every risk item should be traceable back to source evidence whenever possible.
- If the analysis is uncertain, mark it as such instead of forcing a conclusion.
- The schema should be stable enough to map into the Excel template.

## Schema Notes

The exact field list should be aligned with the current Excel template, but the logical contract should stay stable even if the sheet layout changes.

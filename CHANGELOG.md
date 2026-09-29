# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-29

### Added
- Initial release of DuoMind
- OpenAI-compatible server with Jev classification integration
- Interactive setup wizard for non-technical users
- Support for local GGUF models via llama.cpp
- Decision registry with PRE/MID/POST stages
- Jev client with caching, fallback, and circuit breaker
- CLI commands: setup, start, stop, status, logs, doctor, jev, models, uninstall
- Skill registry (webdev, coding, debug, git, webfetch, general) with a Jev-selected PRE `skill` decision and keyword fallback
- Skill instructions injected into the prompt so the model follows task workflows (e.g. fetch a URL before recreating a site) instead of refusing

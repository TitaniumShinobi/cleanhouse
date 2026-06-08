# CleanHouse RTOS Foundation (Intermediary v1)

Last updated: 2026-05-28
Status: Scope lock

## Intermediary core
- Firmware
- Kernel
- I/O system
- Process management
- Memory allocation
- File system and integrity
- Device drivers
- Security and permissions
- Graphical user interface

## Required working surfaces
- Interface
- Zaelith

## Process monitor requirements
- Universal task manager
- Port monitor
- File-change monitor

## File integrity requirements
- Trace who/what/where modified files and when.
- Read agent conversations as context for evidence correlation.
- Auto-sorter toggle: group similar files in directories into generic named folders.
- Universal file cleaner.

## Agent mediator requirements
- Auto-adjust files when necessary (toggle).
- Require confirmation for mediated changes: `Keep changes? [y/n]`.

## Security requirements
- Kill malicious scripts based on observed evidence and configured policy.
- Evolving defense rules from new local evidence.
- Autonomous processes must remain explicit and reviewable.

## Product posture
- `CleanHouse vs The World` remains bounded to local evidence and operator controls.
- No hidden automation; operator can inspect and override every mediated action.

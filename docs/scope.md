# Scope — which head units this covers (and which it does not)

> **Language:** English · [Русский](scope.ru.md)

This library targets the **NBT EVO** head unit: the **QNX**-based iDrive computer used across
BMW F- and early G-series, driving UI generations **ID4 / ID5 / ID6**. Everything here — the HSFZ
transport, the UDS coding flow, the `BMWSigVerify` coding signature, the datagroup layout — is
specific to that platform.

## The generation ladder

| Head unit | OS | UI gen | This library |
|---|---|---|---|
| CIC | QNX | — | no |
| NBT | QNX | ID4 | partial (same family; verify per unit) |
| **NBT EVO** | **QNX** | **ID5 / ID6** | **yes — the target** |
| MGU (Media Graphics Unit) | **Linux** | **ID7 / ID8** (BMW OS 7/8) | **no — different platform** |

## Why ID7 / MGU is out of scope

ID7 is not a newer skin on the same computer — it is a different head unit (**MGU**) running a
**Linux**-based OS (BMW Operating System 7, later 8). Its coding model, its signing/trust scheme,
its diagnostic services and its filesystem are all different from NBT EVO's QNX world. None of the
primitives here transfer. Supporting MGU would be a separate project, not a catalog addition.

## What *does* transfer within NBT EVO

The **mechanism** is constant across NBT EVO builds — the coding signature math, the write
choreography, the transport. What changes per unit is **data**: the bootloader (BTLD) id that
selects the signing key, and the per-**CAFD** map of which bits mean what. So the code is written
once; support for a new car is a new **catalog** (see [../catalogs/](../catalogs/)), not new code.

Always read the unit's **SVK** (`22 F1 01`) first and key off its real BTLD + CAFD ids — never
assume them from the model year.

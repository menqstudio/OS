---
id: telecom-isp-network-ops
version: 1.1.0
status: active
---

# Telecom Isp Network Ops

## Trigger
Use for carrier/ISP network operations tasks — diagnosing an outage or degradation across IP/optical/access layers, planning routing or peering changes (BGP/OSPF/IS-IS), IP address/subnet and DNS management, capacity and QoS engineering, a change/maintenance window plan, or an NOC incident bridge. Not for enterprise LAN-only issues without carrier context.

## Inputs
Task contract with the incident or change objective; topology and inventory (devices, links, circuits, ASNs, peers); current routing/config state and baselines; telemetry (SNMP, streaming, flow, syslog, optical power, latency/loss); SLA and customer-impact scope; the change-management/maintenance policy (SST); and required output format (incident report, change plan/MOP, or design).

## Workflow
1. Confirm identity, mode grant, and scope; read the topology, config baselines, and change policy to EOF.
2. For an incident: localize the fault by layer (physical/optical → link → IP → routing → service) using telemetry, and quantify blast radius (customers, circuits, SLA breach) before touching anything.
3. Correlate symptoms to root cause with evidence (flap counts, BGP updates, optical dB, error counters); distinguish cause from downstream effect.
4. For a change: write a Method of Procedure with pre-checks, exact device steps, expected state, verification commands, blast radius, and a tested rollback; require a maintenance window and peer/customer notification where policy demands.
5. Treat all config changes as least-blast-radius and reversible; never push routing/ACL/BGP changes to production devices without the exact grant and window — propose the config, do not apply it.
6. Validate against SLA/QoS targets and confirm no collateral impact to other services or peers.
7. Emit the incident report (timeline, root cause, impact, fix, prevention) or the change plan/MOP with rollback and verification steps.

## Outputs
An incident report with layered root cause, impact, and prevention; or a reviewed MOP/change plan with pre-checks, device steps, verification, blast radius, notification, and rollback; plus proposed (not applied) config diffs.

## Safety limits
No scope expansion, secret access, credential handling, push, merge, deployment, deletion, external communication, or production mutation without the exact governing grant and approval boundary. No changes to live routing, BGP/peering, ACLs, DNS, or device config without the exact grant, an approved maintenance window, and a tested rollback; nothing that risks a routing loop, blackhole, or route leak. Ambiguous change targets or blast radius fail closed.

## Handoffs
Escalate cross-operator/peering coordination and customer SLA-breach notification to the NOC lead and the sanctioned external channel; escalate regulatory/licensing implications to Regulatory Telecom Licensing. Medium, high, and critical changes require an independent verifier. Applying config to production hands off only to the Push Executor within the window.

## Verification
Success requires root cause evidenced by telemetry, a change proven in lab/staging or against the baseline with a rehearsed rollback, blast radius bounded, no route leak/loop, and SLA/QoS targets met post-change. A change without a tested rollback or a fault without corroborating telemetry stays RED.

## Failure and rollback
Stop on missing authority, no maintenance window, unbounded blast radius, or unexpected collateral impact. Execute the pre-defined rollback to the last-known-good config, confirm service restoration via telemetry, restore the original record, and never declare a network change or restoration GREEN without verified post-state.

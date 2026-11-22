# FieldMind end-to-end run

Model `fieldmind`, mode `extractive`, selector `reranker`, 23 in-scope + 12 out-of-scope questions.

- In-scope answered: 23/23; reasons: {'ok': 23}
- In-scope answers with the key fact: 21/23
- In-scope answers quoting the manual sentence verbatim (old metric): 19/23
- Answers contradicting the manual: 0
- Answered: time to first sentence median 0.7 s, max 1.0 s; total median 0.7 s, max 1.0 s
- Out-of-scope escalated: 12/12

| # | question | outcome | expected fact | first sentence s | total s | answer |
|---|---|---|---|---|---|---|
| 1 | how much leakage is okay on the pump packing | ok | yes | 0.7 | 0.7 | Packing. Check for leakage around the packing and adjust it according to the instructions of the pump and packing manufacturers. Allowable leakage is usually between 2 and 60 drops per minute. Add packing rings or, if ne |
| 2 | how often do the pump bearings need lubricating | ok | yes | 0.7 | 0.7 | Bearing Lubrication. Bearings should be lubricated semiannually or annually. |
| 3 | what happens if I put too much grease in the bearings | ok | yes | 0.8 | 0.8 | For grease-lubricated bearings, add grease as described in the technical manual for the pump. Be careful not to overgrease bearings, because this interferes with the ball or roller motion and might cause overheating. |
| 4 | what's the difference between NPSHA and NPSHR | ok | yes | 0.7 | 0.7 | There are two principal references to NPSH: (1) the available system pressure (NPSHA) at the inlet, which is a function of the system and the flow rate, and (2) the required pressure (NPSHR), which is a function of the p |
| 5 | how far can we trim down an impeller | ok | no | 0.6 | 0.6 | A pump is operating far from its design point. Effect of Impeller Trimming on Pump Performance example, a 2% reduction in the impeller diameter creates about a 2% reduction in flow, a 4% reduction in head, and an 8% redu |
| 6 | what is a pony pump used for | ok | yes | 0.7 | 0.7 | The large pumps would then be used occasionally only to handle severe load conditions, providing considerable cost savings. The pony pump typically handles normal system requirements, while the larger pump is used during |
| 7 | what happens if all the valves after a positive displacement pump are closed | ok | no | 0.5 | 0.5 | If valves in the pumping system are aligned so that all the discharge lines downstream of a pump are closed while the pump is operating, overpressure conditions can occur quickly. |
| 8 | how do I check the mechanical seal during maintenance | ok | yes | 0.6 | 0.6 | Mechanical Seals. Check for leakage. If leakage exceeds the manufacturer’s specifications, replace the seal. |
| 9 | how do I check the motor condition | ok | yes | 0.6 | 0.6 | Motor Condition. Check the integrity of motor winding insulation. These tests usually measure insulation resistance at a certain voltage or the rate at which an applied voltage decays across the insulation. A vibration a |
| 10 | why does running at low flow damage the impeller | ok | yes | 0.6 | 0.6 | Internal recirculation tends to occur at low flow rates when fluid leaving the impeller forms damaging vortices. Operating the system at low flow rates can establish damaging flow patterns in either the suction or discha |
| 11 | what is the best efficiency point of a pump | ok | yes | 0.5 | 0.5 | Every centrifugal pump has a BEP—the point at which its operating efficiency is highest and its radial bearing loads are lowest. A pump’s BEP is a function of its inlet configuration, impeller design, casing design, and  |
| 12 | should I start the centrifugal pump with the discharge valves closed | ok | yes | 1.0 | 1.0 | Starting a centrifugal pump while it is deadheaded and then opening the valves soon after the pump comes up to speed can reduce electrical stresses on the motor and the motor controller. |
| 13 | what's wrong with using a bypass valve to control flow | ok | yes | 0.5 | 0.5 | A major drawback of bypass valves is their detrimental impact on system efficiency. The power used to pump the bypassed fluid is wasted. |
| 14 | what should the piping look like right before the pump inlet | ok | yes | 0.5 | 0.5 | First, to establish a uniform-velocity flow profile upstream of the pump, the operator should make sure that a straight run of pipe leads into the pump inlet. |
| 15 | what are wear rings for | ok | yes | 0.7 | 0.7 | Wear rings are used in centrifugal pumps to establish clearances between impellers and pump casings or other impellers. Wear rings are sized to establish a certain gap between the high- and low-pressure sides of an impel |
| 16 | how can I tell if a pump is oversized | ok | yes | 0.7 | 0.7 | There are five common indications that a pump is oversized: excessive flow noise, highly throttled flow control valves, heavy use of bypass lines, frequent replacements of bearings and seals, and intermittent pump operat |
| 17 | which type of adjustable speed drive is most common | ok | yes | 0.7 | 0.7 | VFDs are the most common type of adjustable speed drives and can significantly reduce energy use by matching the speed of driven equipment to required output. |
| 18 | why does the fluid boil inside the pump | ok | yes | 0.7 | 0.7 | At this point, the fluid “boils,” changing from a liquid to a vapor. Known as cavitation, this effect can severely impact a pump’s performance. As the fluid changes phase during cavitation, tiny bubbles form. |
| 19 | what is static head | ok | yes | 0.9 | 0.9 | Static head is the pressure of the fluid in the system, and is the quantity measured by conventional pressure gauges. |
| 20 | what do the affinity laws describe | ok | yes | 0.7 | 0.7 | Affinity laws – A set of relationships that tie together pump performance characteristics such as pressure, flow, and pump speed. |
| 21 | how do I know if a bearing is worn | ok | yes | 0.7 | 0.7 | Bearings. Determine the condition of the bearing by listening for noises that indicate excessive wear, measuring the bearing’s operating temperature, and using a predictive maintenance technique such as vibration analysi |
| 22 | where did Sagar study | ok | yes | 0.6 | 0.6 | Sagar studied Smart Systems at Hochschule Furtwangen University, graduating with an M.Sc. in 2024. |
| 23 | what is FieldMind | ok | yes | 0.4 | 0.4 | Sagar built FieldMind, an air-gapped AI voice assistant that answers field operators' questions from equipment manuals. |
| 24 | what's the weather in Berlin tomorrow | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 25 | how do I reset my email password | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 26 | who won the last football world cup | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 27 | what torque should I use on the gearbox cover bolts | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 28 | how do I bake sourdough bread | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 29 | what is the boiling point of ammonia | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 30 | how do I configure a Siemens S7 PLC | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 31 | tell me a joke | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 32 | what is the capital of France | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 33 | how do I change the oil in my car | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 34 | how many vacation days do I have left | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |
| 35 | what's the wiring colour code for a three phase motor in Germany | low_retrieval_confidence | escalated | 0.0 | 0.0 | I can't answer that reliably from the manuals. I'm passing this to a specialist. |

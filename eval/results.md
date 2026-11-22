
| strategy | retrieval | hit@1 | hit@3 | MRR@3 | chunks | avg words | max words | truncated | ctx words (top-3) |
|---|---|---|---|---|---|---|---|---|---|
| line | dense | 0.13 | 0.26 | 0.19 | 6863 | 7 | 136 | 0% | 31 |
| line | hybrid | 0.13 | 0.17 | 0.15 | 6863 | 7 | 136 | 0% | 29 |
| fixed | dense | 0.43 | 0.65 | 0.53 | 473 | 120 | 120 | 0% | 355 |
| fixed | hybrid | 0.39 | 0.83 | 0.59 | 473 | 120 | 120 | 0% | 355 |
| sentence | dense | 0.52 | 0.65 | 0.57 | 872 | 72 | 195 | 0% | 212 |
| sentence | hybrid | 0.43 | 0.70 | 0.55 | 872 | 72 | 195 | 0% | 213 |
| recursive | dense | 0.39 | 0.83 | 0.57 | 430 | 110 | 160 | 1% | 323 |
| recursive | hybrid | 0.30 | 0.87 | 0.56 | 430 | 110 | 160 | 1% | 337 |
| semantic | dense | 0.35 | 0.61 | 0.46 | 655 | 72 | 160 | 1% | 254 |
| semantic | hybrid | 0.39 | 0.61 | 0.49 | 655 | 72 | 160 | 1% | 289 |
| section | dense | 0.39 | 0.70 | 0.52 | 462 | 111 | 160 | 1% | 332 |
| section | hybrid | 0.30 | 0.87 | 0.53 | 462 | 111 | 160 | 1% | 345 |

Misses (no relevant chunk in top-k):
  line/dense: ['how often do the pump bearings need lubricating', "what's the difference between NPSHA and NPSHR", 'how far can we trim down an impeller', 'what is a pony pump used for', 'what happens if all the valves after a positive displacement pump are closed', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what is the best efficiency point of a pump', 'should I start the centrifugal pump with the discharge valves closed', "what's wrong with using a bypass valve to control flow", 'what should the piping look like right before the pump inlet', 'what are wear rings for', 'how can I tell if a pump is oversized', 'which type of adjustable speed drive is most common', 'why does the fluid boil inside the pump', 'what do the affinity laws describe', 'where did Sagar study']
  line/hybrid: ['how often do the pump bearings need lubricating', "what's the difference between NPSHA and NPSHR", 'how far can we trim down an impeller', 'what is a pony pump used for', 'what happens if all the valves after a positive displacement pump are closed', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what is the best efficiency point of a pump', 'should I start the centrifugal pump with the discharge valves closed', "what's wrong with using a bypass valve to control flow", 'what should the piping look like right before the pump inlet', 'what are wear rings for', 'how can I tell if a pump is oversized', 'which type of adjustable speed drive is most common', 'why does the fluid boil inside the pump', 'what is static head', 'what do the affinity laws describe', 'how do I know if a bearing is worn', 'where did Sagar study']
  fixed/dense: ['how much leakage is okay on the pump packing', 'how often do the pump bearings need lubricating', 'how far can we trim down an impeller', 'what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', "what's wrong with using a bypass valve to control flow", 'what should the piping look like right before the pump inlet']
  fixed/hybrid: ['how much leakage is okay on the pump packing', 'how far can we trim down an impeller', "what's wrong with using a bypass valve to control flow", 'what should the piping look like right before the pump inlet']
  sentence/dense: ['what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'should I start the centrifugal pump with the discharge valves closed', "what's wrong with using a bypass valve to control flow", 'what should the piping look like right before the pump inlet', 'which type of adjustable speed drive is most common', 'what is static head']
  sentence/hybrid: ['how far can we trim down an impeller', 'what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', "what's wrong with using a bypass valve to control flow", 'what are wear rings for', 'how can I tell if a pump is oversized']
  recursive/dense: ['what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what should the piping look like right before the pump inlet']
  recursive/hybrid: ['what is a pony pump used for', 'what should the piping look like right before the pump inlet', 'how can I tell if a pump is oversized']
  semantic/dense: ['what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what is the best efficiency point of a pump', 'should I start the centrifugal pump with the discharge valves closed', 'what should the piping look like right before the pump inlet', 'how can I tell if a pump is oversized', 'which type of adjustable speed drive is most common', 'where did Sagar study']
  semantic/hybrid: ['how often do the pump bearings need lubricating', 'how far can we trim down an impeller', 'what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what should the piping look like right before the pump inlet', 'how can I tell if a pump is oversized', 'which type of adjustable speed drive is most common', 'where did Sagar study']
  section/dense: ['how much leakage is okay on the pump packing', 'how far can we trim down an impeller', 'what is a pony pump used for', 'how do I check the mechanical seal during maintenance', 'why does running at low flow damage the impeller', 'what should the piping look like right before the pump inlet', 'which type of adjustable speed drive is most common']
  section/hybrid: ['how much leakage is okay on the pump packing', 'how far can we trim down an impeller', 'why does running at low flow damage the impeller']

Best-match cosine (section chunks):
  in-scope     min=0.212  p10=0.424  median=0.595
  out-of-scope max=0.351  p90=0.325  median=0.185
  threshold | in-scope refused | out-of-scope answered
  0.200     |  0/23            |  6/12
  0.225     |  1/23            |  5/12
  0.250     |  1/23            |  5/12
  0.275     |  2/23            |  5/12
  0.300     |  2/23            |  2/12
  0.325     |  2/23            |  2/12
  0.350     |  2/23            |  1/12
  0.375     |  2/23            |  0/12
  0.400     |  2/23            |  0/12
  0.425     |  3/23            |  0/12
  0.450     |  3/23            |  0/12
  0.475     |  3/23            |  0/12
  0.500     |  4/23            |  0/12
  0.525     |  4/23            |  0/12
  0.550     |  5/23            |  0/12
  0.575     |  8/23            |  0/12
  0.600     | 13/23            |  0/12

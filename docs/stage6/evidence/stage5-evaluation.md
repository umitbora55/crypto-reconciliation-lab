# Synthetic unresolved-at-horizon evaluation

Target: scope still open at T+24h. Known-label recall is not complete censored recall.
Unknown labels retain queue positions and capacity; there is no refill.

## test

No additional benefit demonstrated in this synthetic experiment.

| Policy | N | K | P | TP | FP | U | Recall known | Precision labeled | Precision bounds | Coverage |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| fifo | 78 | 16 | 36 | 7 | 8 | 1 | 0.19444444444444445 | 0.4666666666666667 | [0.4375, 0.5] | 0.9375 |
| rules | 78 | 16 | 36 | 8 | 8 | 0 | 0.2222222222222222 | 0.5 | [0.5, 0.5] | 1.0 |
| model | 78 | 16 | 36 | 8 | 8 | 0 | 0.2222222222222222 | 0.5 | [0.5, 0.5] | 1.0 |

Model minus rules Recall_known: 0.0

### Saved-evidence review examples

- ea44328fc30eccc61::ASSET_A: known_positive_missed_by_model; 966a94e08eb2ac0c5c5c87d1377e2c0b39e3684c6a9f4bdc33a290bd019ac1c4:/findings/0, 966a94e08eb2ac0c5c5c87d1377e2c0b39e3684c6a9f4bdc33a290bd019ac1c4:/findings/1, 966a94e08eb2ac0c5c5c87d1377e2c0b39e3684c6a9f4bdc33a290bd019ac1c4:/findings/2, 966a94e08eb2ac0c5c5c87d1377e2c0b39e3684c6a9f4bdc33a290bd019ac1c4:/findings/3, 966a94e08eb2ac0c5c5c87d1377e2c0b39e3684c6a9f4bdc33a290bd019ac1c4:/findings/4
- ec2437632e3415f19::ASSET_B: known_positive_missed_by_model; 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/7, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/8, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/9, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/10, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/11, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/12, 28fde803563d90d3ff4ed473879162e51e104d86ad0002bf6c2daec131d9b4e3:/findings/13
- e2f1a35d45dc4bdd2::ASSET_A: known_positive_missed_by_model; ebf48571d050e61e873def455d97577d92fc728d40ea92f7bc7276b95f24fba7:/findings/0, ebf48571d050e61e873def455d97577d92fc728d40ea92f7bc7276b95f24fba7:/findings/1, ebf48571d050e61e873def455d97577d92fc728d40ea92f7bc7276b95f24fba7:/findings/2, ebf48571d050e61e873def455d97577d92fc728d40ea92f7bc7276b95f24fba7:/findings/3, ebf48571d050e61e873def455d97577d92fc728d40ea92f7bc7276b95f24fba7:/findings/4
- ef901378a092f0496::ASSET_B: known_positive_missed_by_model; 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/6, 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/7, 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/8, 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/9, 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/10, 54d5cbfd5b534fc225d45370e8b845de3dd2ce7666fd4d0e03962ed31bf36e0d:/findings/11
- ec3e442ec2fefb222::ASSET_A: known_positive_missed_by_model; 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/0, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/1, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/2, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/3, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/4, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/5, 6ad664061ae60e87a80598b92d9509acbd386f4a0aa55a09f985b8f58013b6a4:/findings/6

World/family/asset attribution and all raw denominators are in metrics.json.

## challenge

No additional benefit demonstrated in this synthetic experiment.

| Policy | N | K | P | TP | FP | U | Recall known | Precision labeled | Precision bounds | Coverage |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| fifo | 96 | 20 | 48 | 11 | 9 | 0 | 0.22916666666666666 | 0.55 | [0.55, 0.55] | 1.0 |
| rules | 96 | 20 | 48 | 10 | 10 | 0 | 0.20833333333333334 | 0.5 | [0.5, 0.5] | 1.0 |
| model | 96 | 20 | 48 | 9 | 11 | 0 | 0.1875 | 0.45 | [0.45, 0.45] | 1.0 |

Model minus rules Recall_known: -0.020833333333333343

### Saved-evidence review examples

- e4634f5e51f49f242::ASSET_A: known_positive_missed_by_model; 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/0, 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/1, 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/2, 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/3, 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/4, 40c2e057e6a821f3c1b75ce7c92ff039b561e02742ea8933fdfdaeae659c69cb:/findings/5
- e554fb0cb16672a2a::ASSET_B: known_positive_missed_by_model; 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/6, 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/7, 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/8, 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/9, 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/10, 001dc851eb85bb0d5d7ee492cfb2d0e8d2618c60fe13a36205e2e20b096f8f21:/findings/11
- e86e47b6d87ac6bfb::ASSET_B: known_positive_missed_by_model; c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/7, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/8, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/9, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/10, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/11, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/12, c8d81e10572e8eabd769c147cdfa4b9077f48f27a6db2251d1626074ed722637:/findings/13
- e08f349a6d67ea07e::ASSET_A: known_positive_missed_by_model; c0a54e587454885e7a525f761555c76c41179c080a374307d9d447ff9ed3afe8:/findings/0, c0a54e587454885e7a525f761555c76c41179c080a374307d9d447ff9ed3afe8:/findings/1, c0a54e587454885e7a525f761555c76c41179c080a374307d9d447ff9ed3afe8:/findings/2, c0a54e587454885e7a525f761555c76c41179c080a374307d9d447ff9ed3afe8:/findings/3, c0a54e587454885e7a525f761555c76c41179c080a374307d9d447ff9ed3afe8:/findings/4
- eceed047881a4ce43::ASSET_A: known_positive_missed_by_model; c28e531cb32c919056f25a18cec52f8421c82c2e1c0690413c838288d7877673:/findings/0, c28e531cb32c919056f25a18cec52f8421c82c2e1c0690413c838288d7877673:/findings/1, c28e531cb32c919056f25a18cec52f8421c82c2e1c0690413c838288d7877673:/findings/2, c28e531cb32c919056f25a18cec52f8421c82c2e1c0690413c838288d7877673:/findings/3, c28e531cb32c919056f25a18cec52f8421c82c2e1c0690413c838288d7877673:/findings/4

World/family/asset attribution and all raw denominators are in metrics.json.

No claim of institutional benefit, fraud detection, causal explanation or independent-sample statistical certainty.

-- Hand-readable E0 data-platform fixture. It is synthetic and carries no market or PnL claim.
.bail on
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

INSERT INTO ingest_commit
    (commit_seq, commit_id, commit_class, committed_wall_us, writer_clock_id,
     committed_mono_ns, writer_build, prior_commit_digest, commit_digest)
VALUES
    (1, 'cmt_fixture_01', 'fixture', 2000100, 'clock-fixture', '100100', 'fixture-writer-v1', NULL,
     '36a8d45360fc1e22a448bedd3ef25d15cc4651daa29b00d15936f4589f97a28b'),
    (2, 'cmt_fixture_02', 'fixture', 2000200, 'clock-fixture', '100200', 'fixture-writer-v1',
     '36a8d45360fc1e22a448bedd3ef25d15cc4651daa29b00d15936f4589f97a28b',
     '58d73ce9b7156584adb015aa1415490702be5f7d22034099ff706630399fea10'),
    (3, 'cmt_fixture_03', 'fixture', 2000300, 'clock-fixture', '100300', 'fixture-writer-v1',
     '58d73ce9b7156584adb015aa1415490702be5f7d22034099ff706630399fea10',
     '0a9bce9c60e4b08f0e674643480782413d187aae03ac085e5f41ef7739b9c985'),
    (4, 'cmt_fixture_04', 'fixture', 2000400, 'clock-fixture', '100400', 'fixture-writer-v1',
     '0a9bce9c60e4b08f0e674643480782413d187aae03ac085e5f41ef7739b9c985',
     'ea7ace7f6ad284f22e86ec7c31448c5d22a6d0386189718aba6ec12987524fa3'),
    (5, 'cmt_fixture_05', 'fixture', 2000500, 'clock-fixture', '100500', 'fixture-writer-v1',
     'ea7ace7f6ad284f22e86ec7c31448c5d22a6d0386189718aba6ec12987524fa3',
     'de8fe8265d799ca8635d86c14e08b17aae12595cacd4e61b71f54ad135e63d44'),
    (6, 'cmt_fixture_06', 'fixture', 2000600, 'clock-fixture', '100600', 'fixture-writer-v1',
     'de8fe8265d799ca8635d86c14e08b17aae12595cacd4e61b71f54ad135e63d44',
     'c765e3648d9c158cc97f2d60980ac7f22fe7e3476b175caa79a0598899938c74'),
    (7, 'cmt_fixture_07', 'fixture', 2000700, 'clock-fixture', '100700', 'fixture-writer-v1',
     'c765e3648d9c158cc97f2d60980ac7f22fe7e3476b175caa79a0598899938c74',
     'c236483f94716482f8798c0af3796ac8cab1948e26634b294bb8eff143110433'),
    (8, 'cmt_fixture_08', 'fixture', 2000800, 'clock-fixture', '100800', 'fixture-writer-v1',
     'c236483f94716482f8798c0af3796ac8cab1948e26634b294bb8eff143110433',
     'c4885b3bcdf3fb30888a93046f0bcae262bbcf9e1c8a71f62889bcc1341bf9bd'),
    (9, 'cmt_fixture_09', 'fixture', 2000900, 'clock-fixture', '100900', 'fixture-writer-v1',
     'c4885b3bcdf3fb30888a93046f0bcae262bbcf9e1c8a71f62889bcc1341bf9bd',
     '70c1be4fc4768ebae2b99e9293617ea0edf902a84a8464b08fbc4c34649a007f'),
    (10, 'cmt_fixture_10', 'fixture', 2001000, 'clock-fixture', '101000', 'fixture-writer-v1',
     '70c1be4fc4768ebae2b99e9293617ea0edf902a84a8464b08fbc4c34649a007f',
     '3413ae4b631c6ab438574b9c4db33333591802ab224cdaf70f05a092e47e6035'),
    (11, 'cmt_fixture_11', 'fixture', 2001100, 'clock-fixture', '101100', 'fixture-writer-v1',
     '3413ae4b631c6ab438574b9c4db33333591802ab224cdaf70f05a092e47e6035',
     'e2f5fba0f0c4e3967045d0ef96d6de454ae81b53b45a9ca1e33a4ae02711d202'),
    (12, 'cmt_fixture_12', 'fixture', 2001200, 'clock-fixture', '101200', 'fixture-writer-v1',
     'e2f5fba0f0c4e3967045d0ef96d6de454ae81b53b45a9ca1e33a4ae02711d202',
     '0c43a5f6a19a1b6ce84a076e5340e69ce12457a7e1726441b1ebec7c1fb226a7'),
    (13, 'cmt_fixture_13', 'fixture', 2001300, 'clock-fixture', '101300', 'fixture-writer-v1',
     '0c43a5f6a19a1b6ce84a076e5340e69ce12457a7e1726441b1ebec7c1fb226a7',
     '3886920ffd579117178e96080666d9be5aa02a0e047014cdf0f4e0ee1ede9e16');

INSERT INTO source
    (source_id, namespace, source_contract_version, collector_build,
     configuration_fingerprint, effect_ceiling)
VALUES
    ('src_fixture_chain', 'fixture.chain', '1', 'fixture-collector-v1',
     'bae4de2fee9730bf3473e68d99dcd04dd520e8abc73dde69ee5ca514cd74d60e',
     'observe_only'),
    ('src_fixture_operator', 'fixture.operator', '1', 'fixture-ui-v1',
     '2414f10f64248c8cc1da46e51a7d2df38ab87509c02a5feda0d4173a307ea031',
     'observe_only');

INSERT INTO acquisition
    (acquisition_id, source_id, acquisition_kind, transport_kind, registered_commit_seq,
     parent_acquisition_id, request_fingerprint, started_wall_us, local_clock_id,
     started_mono_ns, source_locator_redacted)
VALUES
    ('acq_chain_primary', 'src_fixture_chain', 'fixture', 'fixture', 1, NULL,
     '36a8d45360fc1e22a448bedd3ef25d15cc4651daa29b00d15936f4589f97a28b',
     2000000, 'clock-fixture', '100000', 'fixture://chain/primary'),
    ('acq_chain_duplicate', 'src_fixture_chain', 'fixture', 'fixture', 2,
     'acq_chain_primary',
     '58d73ce9b7156584adb015aa1415490702be5f7d22034099ff706630399fea10',
     2000150, 'clock-fixture', '100150', 'fixture://chain/redelivery'),
    ('acq_chain_unknown', 'src_fixture_chain', 'fixture', 'fixture', 3, NULL,
     '0a9bce9c60e4b08f0e674643480782413d187aae03ac085e5f41ef7739b9c985',
     2000250, 'clock-fixture', '100250', 'fixture://chain/unknown'),
    ('acq_chain_recovery', 'src_fixture_chain', 'recovery', 'fixture', 5,
     'acq_chain_primary',
     'de8fe8265d799ca8635d86c14e08b17aae12595cacd4e61b71f54ad135e63d44',
     2000450, 'clock-fixture', '100450', 'fixture://chain/recovery'),
    ('acq_chain_correction', 'src_fixture_chain', 'backfill', 'fixture', 8,
     'acq_chain_primary',
     'c4885b3bcdf3fb30888a93046f0bcae262bbcf9e1c8a71f62889bcc1341bf9bd',
     2000750, 'clock-fixture', '100750', 'fixture://chain/correction');

INSERT INTO acquisition_end
    (acquisition_end_id, acquisition_id, ended_commit_seq, ended_wall_us, end_status, detail_code)
VALUES
    ('ace_chain_primary', 'acq_chain_primary', 1, 2000090, 'complete', NULL),
    ('ace_chain_duplicate', 'acq_chain_duplicate', 2, 2000190, 'complete', 'redelivery'),
    ('ace_chain_unknown', 'acq_chain_unknown', 3, 2000290, 'complete', 'unsupported_variant'),
    ('ace_chain_recovery', 'acq_chain_recovery', 6, 2000590, 'complete', 'gap_recovered'),
    ('ace_chain_correction', 'acq_chain_correction', 8, 2000790, 'complete', 'decoder_v2');

INSERT INTO blob
    (blob_id, created_commit_seq, storage_mode, inline_bytes, relative_path,
     content_length, stored_length, stored_sha256, compression, content_type,
     content_encoding, retention_class)
VALUES
    ('9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163', 1,
     'external', NULL,
     'fixtures/tape/blobs/sha256/9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163.blob',
     216, 216, '9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('b6d35637158ced08f1ec3da5c3e6f7671f312f38d6e1cdd6f0ec83bd2f4d2eef', 3,
     'external', NULL,
     'fixtures/tape/blobs/sha256/b6d35637158ced08f1ec3da5c3e6f7671f312f38d6e1cdd6f0ec83bd2f4d2eef.blob',
     77, 77, 'b6d35637158ced08f1ec3da5c3e6f7671f312f38d6e1cdd6f0ec83bd2f4d2eef',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('70c4eaa98d6cfa0a0f6771fe815b40380ed46931ab9ca2f8116fbb13e37e255e', 5,
     'external', NULL,
     'fixtures/tape/blobs/sha256/70c4eaa98d6cfa0a0f6771fe815b40380ed46931ab9ca2f8116fbb13e37e255e.blob',
     143, 143, '70c4eaa98d6cfa0a0f6771fe815b40380ed46931ab9ca2f8116fbb13e37e255e',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('1dddf91700fb4cc9c9de512b80ba350edb1ac7335c5324d5c94609b68851ebd9', 6,
     'external', NULL,
     'fixtures/tape/blobs/sha256/1dddf91700fb4cc9c9de512b80ba350edb1ac7335c5324d5c94609b68851ebd9.blob',
     143, 143, '1dddf91700fb4cc9c9de512b80ba350edb1ac7335c5324d5c94609b68851ebd9',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('e678b843e8e3036b7b9869aa694d10973abe62732ce01e753a1b7f2726db202a', 8,
     'external', NULL,
     'fixtures/tape/blobs/sha256/e678b843e8e3036b7b9869aa694d10973abe62732ce01e753a1b7f2726db202a.blob',
     136, 136, 'e678b843e8e3036b7b9869aa694d10973abe62732ce01e753a1b7f2726db202a',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f', 7,
     'external', NULL,
     'fixtures/tape/blobs/sha256/a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f.blob',
     187, 187, 'a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('a3d68a6735232487e94c561b57fd10cf1b8c5dc03d1323e996eb0427040e4ffc', 12,
     'external', NULL,
     'fixtures/tape/blobs/sha256/a3d68a6735232487e94c561b57fd10cf1b8c5dc03d1323e996eb0427040e4ffc.blob',
     223, 223, 'a3d68a6735232487e94c561b57fd10cf1b8c5dc03d1323e996eb0427040e4ffc',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('e63b333a8db00de7dd3f7d0aeb32079d0aa5d29b88525a4e815ab6e94a8464a7', 7,
     'external', NULL,
     'fixtures/tape/blobs/sha256/e63b333a8db00de7dd3f7d0aeb32079d0aa5d29b88525a4e815ab6e94a8464a7.blob',
     119, 119, 'e63b333a8db00de7dd3f7d0aeb32079d0aa5d29b88525a4e815ab6e94a8464a7',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('587af6f405fa2431054b685b26694d40849ee55afce3da720a950e723b45ebc3', 9,
     'external', NULL,
     'fixtures/tape/blobs/sha256/587af6f405fa2431054b685b26694d40849ee55afce3da720a950e723b45ebc3.blob',
     112, 112, '587af6f405fa2431054b685b26694d40849ee55afce3da720a950e723b45ebc3',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('93800bd6452115cee7e65a402dc0a2bcac972323cde57487639c5e5859ca67d7', 10,
     'external', NULL,
     'fixtures/tape/blobs/sha256/93800bd6452115cee7e65a402dc0a2bcac972323cde57487639c5e5859ca67d7.blob',
     93, 93, '93800bd6452115cee7e65a402dc0a2bcac972323cde57487639c5e5859ca67d7',
     'identity', 'application/json', 'utf-8', 'fixture'),
    ('32b0906e2d191157ec36b32d6e06ae8847b08c4f0b53d6cd4b3709aad892dc45', 11,
     'external', NULL,
     'fixtures/tape/blobs/sha256/32b0906e2d191157ec36b32d6e06ae8847b08c4f0b53d6cd4b3709aad892dc45.blob',
     110, 110, '32b0906e2d191157ec36b32d6e06ae8847b08c4f0b53d6cd4b3709aad892dc45',
     'identity', 'application/json', 'utf-8', 'fixture');

INSERT INTO observation
    (observation_id, commit_seq, intra_commit_seq, acquisition_id, acquisition_ordinal,
     source_id, blob_id, observation_kind, received_wall_us, received_clock_id,
     received_mono_ns, persisted_wall_us, available_wall_us, event_time_status,
     source_event_lower_us, source_event_upper_us, source_time_precision_us,
     chain_slot, chain_tx_index, chain_instruction_path, chain_log_index, chain_commitment,
     source_cursor_text, parse_disposition, quality_code)
VALUES
    ('obs_equal_primary', 1, 0, 'acq_chain_primary', 0, 'src_fixture_chain',
     '9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163',
     'fixture', 2000010, 'clock-fixture', '100010', 2000090, 2000090,
     'exact', 1000000, 1000001, 1, 100, 0, '0', NULL, 'finalized', 'slot:100',
     'decoded', NULL),
    ('obs_equal_redelivery', 2, 0, 'acq_chain_duplicate', 0, 'src_fixture_chain',
     '9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163',
     'fixture', 2000160, 'clock-fixture', '100160', 2000190, 2000190,
     'exact', 1000000, 1000001, 1, 100, 0, '0', NULL, 'finalized', 'slot:100',
     'decoded', 'duplicate_delivery'),
    ('obs_unknown_variant', 3, 0, 'acq_chain_unknown', 0, 'src_fixture_chain',
     'b6d35637158ced08f1ec3da5c3e6f7671f312f38d6e1cdd6f0ec83bd2f4d2eef',
     'fixture', 2000260, 'clock-fixture', '100260', 2000290, 2000290,
     'source_missing', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
     'unsupported_variant', 'future_variant_preserved_raw'),
    ('obs_recovery_101', 5, 0, 'acq_chain_recovery', 0, 'src_fixture_chain',
     '70c4eaa98d6cfa0a0f6771fe815b40380ed46931ab9ca2f8116fbb13e37e255e',
     'fixture', 2000460, 'clock-fixture', '100460', 2000490, 2000490,
     'exact', 1000100, 1000101, 1, 101, 0, '0', NULL, 'finalized', 'slot:101',
     'decoded', 'gap_recovery'),
    ('obs_recovery_102', 6, 0, 'acq_chain_recovery', 1, 'src_fixture_chain',
     '1dddf91700fb4cc9c9de512b80ba350edb1ac7335c5324d5c94609b68851ebd9',
     'fixture', 2000560, 'clock-fixture', '100560', 2000590, 2000590,
     'exact', 1000200, 1000201, 1, 102, 0, '0', NULL, 'finalized', 'slot:102',
     'decoded', 'gap_recovery'),
    ('obs_equal_correction', 8, 0, 'acq_chain_correction', 0, 'src_fixture_chain',
     'e678b843e8e3036b7b9869aa694d10973abe62732ce01e753a1b7f2726db202a',
     'fixture', 2000760, 'clock-fixture', '100760', 2000790, 2000790,
     'exact', 1000000, 1000001, 1, 100, 0, '0', 0, 'finalized', 'slot:100/event:0',
     'decoded', 'late_decoder_correction');

INSERT INTO source_event
    (source_event_id, source_id, event_namespace, natural_key, identified_commit_seq, source_order_key)
VALUES
    ('sev_equal_trade_0', 'src_fixture_chain', 'fixture.trade',
     'fixture|sig-equal|event=0', 1, 'slot=100;tx=0;event=0'),
    ('sev_equal_trade_1', 'src_fixture_chain', 'fixture.trade',
     'fixture|sig-equal|event=1', 1, 'slot=100;tx=0;event=1'),
    ('sev_recovery_trade_101', 'src_fixture_chain', 'fixture.trade',
     'fixture|sig-recover-101|event=0', 5, 'slot=101;tx=0;event=0'),
    ('sev_recovery_trade_102', 'src_fixture_chain', 'fixture.trade',
     'fixture|sig-recover-102|event=0', 6, 'slot=102;tx=0;event=0');

INSERT INTO observation_source_event
    (observation_id, source_event_id, relation, event_ordinal)
VALUES
    ('obs_equal_primary', 'sev_equal_trade_0', 'contains', 0),
    ('obs_equal_primary', 'sev_equal_trade_1', 'contains', 1),
    ('obs_equal_redelivery', 'sev_equal_trade_0', 'contains', 0),
    ('obs_equal_redelivery', 'sev_equal_trade_1', 'contains', 1),
    ('obs_recovery_101', 'sev_recovery_trade_101', 'contains', 0),
    ('obs_recovery_102', 'sev_recovery_trade_102', 'contains', 0),
    ('obs_equal_correction', 'sev_equal_trade_0', 'revision', 0);

INSERT INTO assertion
    (assertion_id, semantic_key, assertion_kind, producer_id, producer_version,
     produced_commit_seq, produced_wall_us, valid_time_status, valid_lower_us,
     valid_upper_us, assertion_status, value_json, value_sha256, supersedes_assertion_id)
VALUES
    ('ast_trade_0_v1', 'fixture:trade:sig-equal:0', 'protocol.trade',
     'fixture-decoder', '1', 1, 2000095, 'exact', 1000000, 1000001, 'accepted',
     '{"kind":"trade","base_atoms":"100","quote_atoms":"25"}',
     'bc60e6b05a12969bd3e13ca7a1ab7fda329647ca69bdac5707d3635b39aaebce', NULL),
    ('ast_trade_1_v1', 'fixture:trade:sig-equal:1', 'protocol.trade',
     'fixture-decoder', '1', 1, 2000096, 'exact', 1000000, 1000001, 'accepted',
     '{"kind":"trade","base_atoms":"100","quote_atoms":"25"}',
     'bc60e6b05a12969bd3e13ca7a1ab7fda329647ca69bdac5707d3635b39aaebce', NULL),
    ('ast_runner_retained', 'fixture:episode:runner:1', 'operator.stance',
     'fixture-reducer', '1', 7, 2000695, 'exact', 1000600, 1000601, 'accepted',
     '{"episode_id":"episode-fixture","transition":"runner_retained","inventory_epoch_id":"epoch-a","remaining_atoms":"400"}',
     '6cef639393768d333d2d096da1b2cf5a0764d100e0a06dc5dd22d4bbd23b9e44', NULL),
    ('ast_trade_0_v2', 'fixture:trade:sig-equal:0', 'protocol.trade',
     'fixture-decoder', '2', 8, 2000795, 'exact', 1000000, 1000001, 'accepted',
     '{"kind":"trade","base_atoms":"100","quote_atoms":"26"}',
     '4fba612923e27e8a0b0a55eda2f061069a14a7e7e7c14888e25de34aabbbc53b',
     'ast_trade_0_v1'),
    ('ast_exact_flat', 'fixture:episode:flat:1', 'operator.episode_transition',
     'fixture-reducer', '1', 9, 2000895, 'exact', 1000800, 1000801, 'accepted',
     '{"episode_id":"episode-fixture","transition":"exact_flat","inventory_epoch_id":"epoch-a","remaining_atoms":"0"}',
     '10721b119b06461d44764c800e0f530e7e0e23fea1a97ddc39cadde46553a9cc', NULL),
    ('ast_watching_flat', 'fixture:episode:watch-flat:1', 'operator.watch_state',
     'fixture-reducer', '1', 10, 2000995, 'exact', 1000900, 1000901, 'accepted',
     '{"episode_id":"episode-fixture","transition":"watching_flat","inventory_epoch_id":"epoch-a"}',
     '71925edf23b698c4f3da95068c56c41ab0233fb96be299000ee18c0df85d7d9c', NULL),
    ('ast_reentry', 'fixture:episode:reentry:1', 'operator.episode_transition',
     'fixture-reducer', '1', 11, 2001095, 'exact', 1001000, 1001001, 'accepted',
     '{"episode_id":"episode-fixture","transition":"reentry","inventory_epoch_id":"epoch-b","acquired_atoms":"125"}',
     'f23ab59f5e96471f6808100bb4e139cef6123addad2e539ae4bfa0f4472fdfc4', NULL);

INSERT INTO assertion_observation_evidence
    (assertion_id, observation_id, evidence_role)
VALUES
    ('ast_trade_0_v1', 'obs_equal_primary', 'decoded_from'),
    ('ast_trade_1_v1', 'obs_equal_primary', 'decoded_from'),
    ('ast_trade_0_v2', 'obs_equal_correction', 'decoded_from');

INSERT INTO assertion_source_event (assertion_id, source_event_id, relation)
VALUES
    ('ast_trade_0_v1', 'sev_equal_trade_0', 'claims_about'),
    ('ast_trade_1_v1', 'sev_equal_trade_1', 'claims_about'),
    ('ast_trade_0_v2', 'sev_equal_trade_0', 'claims_about');

INSERT INTO assertion_amount
    (assertion_id, amount_role, asset_namespace, asset_id, signed_atoms, decimals, unit)
VALUES
    ('ast_trade_0_v1', 'base', 'fixture', 'MintFixture111', '100', 0, 'atoms'),
    ('ast_trade_0_v1', 'quote', 'fixture', 'SOL', '25', 0, 'atoms'),
    ('ast_trade_1_v1', 'base', 'fixture', 'MintFixture111', '100', 0, 'atoms'),
    ('ast_trade_1_v1', 'quote', 'fixture', 'SOL', '25', 0, 'atoms'),
    ('ast_trade_0_v2', 'base', 'fixture', 'MintFixture111', '100', 0, 'atoms'),
    ('ast_trade_0_v2', 'quote', 'fixture', 'SOL', '26', 0, 'atoms'),
    ('ast_runner_retained', 'remaining', 'fixture', 'MintFixture111', '400', 0, 'atoms'),
    ('ast_exact_flat', 'asserted_remaining', 'fixture', 'MintFixture111', '0', 0, 'atoms'),
    ('ast_reentry', 'asserted_acquired', 'fixture', 'MintFixture111', '125', 0, 'atoms');

INSERT INTO coverage_window
    (coverage_id, source_id, acquisition_id, scope_kind, scope_key, manifest_blob_id,
     opened_commit_seq, opened_wall_us, coverage_level)
VALUES
    ('cov_fixture_chain', 'src_fixture_chain', 'acq_chain_primary', 'program',
     'fixture-program', NULL, 1, 2000010, 'fixture');

INSERT INTO coverage_event
    (coverage_event_id, coverage_id, commit_seq, event_kind, occurred_wall_us, detail_code)
VALUES
    ('cve_fixture_open', 'cov_fixture_chain', 1, 'opened', 2000010, NULL),
    ('cve_fixture_gap', 'cov_fixture_chain', 4, 'degraded', 2000390, 'slots_101_102_missing'),
    ('cve_fixture_recovering', 'cov_fixture_chain', 5, 'recovering', 2000490, NULL),
    ('cve_fixture_recovered', 'cov_fixture_chain', 6, 'recovered', 2000590, NULL);

INSERT INTO coverage_gap
    (gap_id, coverage_id, detected_commit_seq, detected_wall_us, cause_code, severity,
     lower_source_locator, upper_source_locator, event_lower_us, event_upper_us)
VALUES
    ('gap_fixture_101_102', 'cov_fixture_chain', 4, 2000390, 'fixture_disconnect',
     'degraded', 'slot:101', 'slot:102', 1000100, 1000201);

INSERT INTO coverage_gap_recovery
    (recovery_id, gap_id, recovery_acquisition_id, commit_seq, recovery_status,
     recovered_through_locator, evidence_blob_id)
VALUES
    ('rcv_fixture_partial', 'gap_fixture_101_102', 'acq_chain_recovery', 5, 'partial',
     'slot:101', '70c4eaa98d6cfa0a0f6771fe815b40380ed46931ab9ca2f8116fbb13e37e255e'),
    ('rcv_fixture_complete', 'gap_fixture_101_102', 'acq_chain_recovery', 6, 'complete',
     'slot:102', '1dddf91700fb4cc9c9de512b80ba350edb1ac7335c5324d5c94609b68851ebd9');

INSERT INTO source_cursor
    (cursor_id, source_id, scope_kind, scope_key, cursor_kind, cursor_value,
     advanced_commit_seq, acquisition_id, primary_evidence_observation_id,
     predecessor_cursor_id, evidence_count)
VALUES
    ('cur_fixture_100', 'src_fixture_chain', 'program', 'fixture-program', 'slot', '100',
     1, 'acq_chain_primary', 'obs_equal_primary', NULL, 1),
    ('cur_fixture_101', 'src_fixture_chain', 'program', 'fixture-program', 'slot', '101',
     5, 'acq_chain_recovery', 'obs_recovery_101', 'cur_fixture_100', 1),
    ('cur_fixture_102', 'src_fixture_chain', 'program', 'fixture-program', 'slot', '102',
     6, 'acq_chain_recovery', 'obs_recovery_102', 'cur_fixture_101', 1);

INSERT INTO source_cursor_evidence (cursor_id, observation_id)
VALUES
    ('cur_fixture_100', 'obs_equal_primary'),
    ('cur_fixture_101', 'obs_recovery_101'),
    ('cur_fixture_102', 'obs_recovery_102');

INSERT INTO scene
    (scene_id, scene_mode, captured_commit_seq, knowledge_cutoff_commit_seq,
     outcome_cutoff_commit_seq, basis_scene_id, client_session_id, client_scene_seq,
     ui_build, view_contract, view_contract_version, source_mode, rendered_wall_us,
     client_clock_id, rendered_mono_ns, view_blob_id, screenshot_blob_id, view_sha256)
VALUES
    ('scn_fixture_witnessed', 'witnessed', 7, 6, NULL, NULL, 'client-fixture', 1,
     'glass-fixture-v1', 'joshi.scene', 1, 'fixture', 2000650, 'browser-fixture', '700',
     'a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f', NULL,
     'a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f'),
    ('scn_fixture_retrospective', 'retrospective', 12, 6, 11, 'scn_fixture_witnessed',
     'client-fixture', 2, 'glass-fixture-v1', 'joshi.scene', 1, 'fixture', 2001150,
     'browser-fixture', '1200',
     'a3d68a6735232487e94c561b57fd10cf1b8c5dc03d1323e996eb0427040e4ffc', NULL,
     'a3d68a6735232487e94c561b57fd10cf1b8c5dc03d1323e996eb0427040e4ffc');

INSERT INTO scene_watermark
    (scene_id, watermark_namespace, source_id, projection_name, projection_version,
     delivered_commit_seq, state_sha256)
VALUES
    ('scn_fixture_witnessed', 'source:fixture-chain', 'src_fixture_chain', NULL, NULL, 6,
     'c765e3648d9c158cc97f2d60980ac7f22fe7e3476b175caa79a0598899938c74'),
    ('scn_fixture_retrospective', 'source:fixture-chain', 'src_fixture_chain', NULL, NULL, 11,
     'e2f5fba0f0c4e3967045d0ef96d6de454ae81b53b45a9ca1e33a4ae02711d202');

INSERT INTO scene_choice_member
    (scene_id, set_kind, subject_kind, subject_key, source_rank, rendered_ordinal,
     evidence_assertion_id)
VALUES
    ('scn_fixture_witnessed', 'eligible', 'mint', 'MintFixture111', 4, NULL, NULL),
    ('scn_fixture_witnessed', 'surfaced', 'mint', 'MintFixture111', 4, NULL, NULL),
    ('scn_fixture_witnessed', 'rendered', 'mint', 'MintFixture111', 4, 0, NULL),
    ('scn_fixture_witnessed', 'viewport', 'mint', 'MintFixture111', 4, 0, NULL),
    ('scn_fixture_witnessed', 'interacted', 'mint', 'MintFixture111', 4, 0, NULL),
    ('scn_fixture_retrospective', 'interacted', 'mint', 'MintFixture111', 4, 0,
     'ast_trade_0_v2');

INSERT INTO command
    (command_id, committed_commit_seq, scene_id, client_session_id, client_command_seq,
     idempotency_key, command_kind, subject_kind, subject_key, payload_blob_id,
     issued_wall_us, client_clock_id, issued_mono_ns, received_wall_us,
     effect_ceiling, authority_class)
VALUES
    ('cmd_fixture_runner', 7, 'scn_fixture_witnessed', 'client-fixture', 1,
     'fixture-runner-retry-key', 'reduce_requested', 'episode', 'episode-fixture',
     'e63b333a8db00de7dd3f7d0aeb32079d0aa5d29b88525a4e815ab6e94a8464a7',
     2000660, 'browser-fixture', '710', 2000680, 'observe_only', 'evidence_only'),
    ('cmd_fixture_flat', 9, NULL, 'client-fixture', 2, 'fixture-flat-key',
     'exit_all_requested', 'episode', 'episode-fixture',
     '587af6f405fa2431054b685b26694d40849ee55afce3da720a950e723b45ebc3',
     2000860, 'browser-fixture', '910', 2000880, 'observe_only', 'evidence_only'),
    ('cmd_fixture_watch_flat', 10, NULL, 'client-fixture', 3, 'fixture-watch-flat-key',
     'watch_started', 'episode', 'episode-fixture',
     '93800bd6452115cee7e65a402dc0a2bcac972323cde57487639c5e5859ca67d7',
     2000960, 'browser-fixture', '1010', 2000980, 'observe_only', 'evidence_only'),
    ('cmd_fixture_reentry', 11, NULL, 'client-fixture', 4, 'fixture-reentry-key',
     'reentry_requested', 'episode', 'episode-fixture',
     '32b0906e2d191157ec36b32d6e06ae8847b08c4f0b53d6cd4b3709aad892dc45',
     2001060, 'browser-fixture', '1110', 2001080, 'observe_only', 'evidence_only');

INSERT INTO assertion_command_evidence
    (assertion_id, command_id, evidence_role)
VALUES
    ('ast_runner_retained', 'cmd_fixture_runner', 'records_operator_claim'),
    ('ast_exact_flat', 'cmd_fixture_flat', 'records_operator_claim'),
    ('ast_watching_flat', 'cmd_fixture_watch_flat', 'records_operator_claim'),
    ('ast_reentry', 'cmd_fixture_reentry', 'records_intent');

INSERT INTO projection_version
    (projection_name, projection_version, producer_build, configuration_sha256,
     schema_sha256, deterministic)
VALUES
    ('fixture.episode', '1', 'fixture-reducer-v1',
     'bae4de2fee9730bf3473e68d99dcd04dd520e8abc73dde69ee5ca514cd74d60e',
     '2414f10f64248c8cc1da46e51a7d2df38ab87509c02a5feda0d4173a307ea031', 1);

INSERT INTO projection_checkpoint
    (checkpoint_id, projection_name, projection_version, through_commit_seq,
     created_commit_seq, input_manifest_sha256, output_sha256)
VALUES
    ('chk_fixture_episode_11', 'fixture.episode', '1', 11, 12,
     'bae4de2fee9730bf3473e68d99dcd04dd520e8abc73dde69ee5ca514cd74d60e',
     '0da092967c32caba79848ca427c2497ae12a2ec902eb0575fc713887c4b05ba2');

INSERT INTO outbox_item
    (outbox_id, enqueued_commit_seq, item_kind, effect_class, payload_blob_id,
     idempotency_key, not_before_wall_us, status, attempt_count, lease_owner,
     lease_expires_wall_us, completed_wall_us, last_error_code)
VALUES
    ('obx_fixture_episode_projection', 7, 'fixture.episode.project', 'projection',
     'e63b333a8db00de7dd3f7d0aeb32079d0aa5d29b88525a4e815ab6e94a8464a7',
     'fixture-projection-through-11', 2000700, 'done', 1, NULL, NULL, 2001190, NULL);

INSERT INTO export_manifest
    (export_manifest_id, family, family_schema_version, generation, part_ordinal,
     projection_name, projection_version, from_commit_seq, through_commit_seq,
     created_commit_seq, input_manifest_sha256, relative_path, file_sha256,
     byte_length, row_count, format, compression, writer_version, schema_sha256,
     event_lower_us, event_upper_us, min_chain_slot, max_chain_slot, retention_class)
VALUES
    ('exp_fixture_episode_01', 'fixture_episode_transitions', 1, 1, 0,
     'fixture.episode', '1', 1, 11, 13,
     'bae4de2fee9730bf3473e68d99dcd04dd520e8abc73dde69ee5ca514cd74d60e',
     'fixtures/tape/exports/92a6a5d1c027425d95c0ffd558861ecbe966a88007fc8bc2d69e10b44d303c96.parquet.fixture',
     '92a6a5d1c027425d95c0ffd558861ecbe966a88007fc8bc2d69e10b44d303c96',
     60, 4, 'fixture_opaque', 'fixture-none', 'fixture-writer-v1',
     '2414f10f64248c8cc1da46e51a7d2df38ab87509c02a5feda0d4173a307ea031',
     1000600, 1001001, NULL, NULL, 'fixture');

INSERT INTO export_snapshot
    (export_snapshot_id, contract, schema_version, manifest_relative_path,
     manifest_sha256, manifest_byte_length, from_commit_seq, through_commit_seq,
     scene_id, created_commit_seq)
VALUES
    ('exs_fixture_episode_01', 'joshi.export_snapshot.fixture.v1', 1,
     'fixtures/tape/exports/snapshot-manifest.json',
     'dd9470b6138f7ef50bc05cd2e8046ca215e51b429e5152f246c29dd8526a7c5e',
     409, 1, 11, 'scn_fixture_witnessed', 13);

INSERT INTO export_snapshot_part (export_snapshot_id, export_manifest_id)
VALUES ('exs_fixture_episode_01', 'exp_fixture_episode_01');

-- V5 lossless contract sidecars. Indexed V1-V4 columns remain the query surface; these preserve
-- fields whose absence or open-world recognition cannot be reconstructed later.
INSERT INTO blob_object
    (blob_id, storage_domain, storage_mode, inline_bytes, relative_path, stored_length,
     stored_sha256, compression)
SELECT blob_id, retention_class, storage_mode, inline_bytes, relative_path, stored_length,
       stored_sha256, compression
FROM blob;

INSERT INTO observation_blob_contract
    (observation_id, blob_id, storage_domain, content_type, content_encoding, retention_class)
SELECT o.observation_id, b.blob_id, b.retention_class, b.content_type, b.content_encoding,
       b.retention_class
FROM observation AS o JOIN blob AS b USING (blob_id);

INSERT INTO scene_artifact_contract (scene_id, artifact_role, blob_id, storage_domain)
SELECT scene_id, 'view', view_blob_id, 'fixture' FROM scene;

INSERT INTO command_payload_contract (command_id, blob_id, storage_domain)
SELECT command_id, payload_blob_id, 'fixture' FROM command;

INSERT INTO acquisition_contract
    (acquisition_id, contract_version, acquisition_kind_recognition,
     transport_kind_recognition, requested_wall_us, received_wall_us, persisted_wall_us,
     elapsed_mono_ns, elapsed_clock_id, source_cursor_text)
SELECT a.acquisition_id, '1', 'known', 'known', a.started_wall_us,
       MIN(o.received_wall_us), MAX(o.persisted_wall_us),
       CAST(MAX(CAST(o.received_mono_ns AS INTEGER)) - CAST(a.started_mono_ns AS INTEGER) AS TEXT),
       a.local_clock_id, MAX(o.source_cursor_text)
FROM acquisition AS a JOIN observation AS o USING (acquisition_id)
GROUP BY a.acquisition_id;

INSERT INTO observation_contract
    (observation_id, observation_kind_recognition, source_variant,
     source_variant_recognition, event_time_status_recognition,
     chain_commitment_recognition, parse_disposition_recognition)
SELECT observation_id, 'known',
       CASE WHEN observation_id = 'obs_unknown_variant'
            THEN 'fixture.future_variant' ELSE 'fixture.transaction' END,
       CASE WHEN observation_id = 'obs_unknown_variant' THEN 'unknown' ELSE 'known' END,
       'known', CASE WHEN chain_commitment IS NULL THEN NULL ELSE 'known' END, 'known'
FROM observation;

INSERT INTO source_event_contract (source_event_id, event_kind, event_kind_recognition)
SELECT source_event_id, 'fixture.trade', 'known' FROM source_event;

INSERT INTO observation_source_event_contract
    (observation_id, source_event_id, relation, relation_recognition)
SELECT observation_id, source_event_id, relation, 'known' FROM observation_source_event;

INSERT INTO assertion_contract
    (assertion_id, assertion_kind_recognition, assertion_status_recognition,
     valid_time_status_recognition, available_wall_us)
SELECT assertion_id, 'known', 'known', 'known', produced_wall_us FROM assertion;

INSERT INTO assertion_observation_evidence_contract
    (assertion_id, observation_id, evidence_role, role_recognition)
SELECT assertion_id, observation_id, evidence_role, 'known'
FROM assertion_observation_evidence;

INSERT INTO assertion_source_event_contract
    (assertion_id, source_event_id, relation, relation_recognition)
SELECT assertion_id, source_event_id, relation, 'known' FROM assertion_source_event;

INSERT INTO assertion_command_evidence_contract
    (assertion_id, command_id, evidence_role, role_recognition)
SELECT assertion_id, command_id, evidence_role, 'known' FROM assertion_command_evidence;

INSERT INTO coverage_window_contract
    (coverage_id, scope_family_recognition, scope_subject, lower_boundary_json,
     upper_boundary_json, state, state_recognition, available_wall_us)
VALUES
    ('cov_fixture_chain', 'known', 'fixture-program',
     '{"clock":"wall","value":"1970-01-01T00:00:02.000010Z"}', NULL,
     'open', 'known', 2000010);

INSERT INTO coverage_gap_contract
    (gap_id, scope_source_id, scope_family, scope_family_recognition, scope_subject,
     lower_boundary_json, upper_boundary_json, reason_recognition)
VALUES
    ('gap_fixture_101_102', 'src_fixture_chain', 'program', 'known', 'fixture-program',
     '{"clock":"source_cursor","value":"slot:101"}',
     '{"clock":"source_cursor","value":"slot:102"}', 'known');

INSERT INTO coverage_recovery_contract
    (recovery_id, status_recognition, recovered_through_json, available_wall_us)
VALUES
    ('rcv_fixture_partial', 'known',
     '{"clock":"source_cursor","value":"slot:101"}', 2000490),
    ('rcv_fixture_complete', 'known',
     '{"clock":"source_cursor","value":"slot:102"}', 2000590);

INSERT INTO coverage_recovery_observation (recovery_id, observation_id)
VALUES
    ('rcv_fixture_partial', 'obs_recovery_101'),
    ('rcv_fixture_complete', 'obs_recovery_101'),
    ('rcv_fixture_complete', 'obs_recovery_102');

INSERT INTO source_cursor_contract
    (cursor_id, scope_family_recognition, scope_subject, cursor_kind_recognition)
SELECT cursor_id, 'known', 'fixture-program', 'known' FROM source_cursor;

COMMIT;

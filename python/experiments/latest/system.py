import os

from constants import ExperimentTypes
from constants.paths import Paths
from experiments.latest.model.coref import NoClusterFeatsPluralACNN
from experiments.latest.model.linking import MentionClusterEntityLinker
from experiments.latest.model.linking_joint import JointMentionClusterEntityLinker
from experiments.latest.tools.ioutils import SpliceReader, StateWriter
from experiments.latest.tools.mention import init_super_mentions
from experiments.latest.tools.state import PluralCorefState
from experiments.latest.tools.evaluators import *
from experiments.system import ExperimentSystem
from util import *
from util.pathutil import *


class LatestSystem(ExperimentSystem):
    def __init__(self, iteration_num=1, use_test_params=True):
        ExperimentSystem.__init__(self, iteration_num, use_test_params)

    def _experiment_type(self):
        return ExperimentTypes.LATEST

    # 以场景为单位，提取共指簇（多个指向同一个角色的mentions集合）、簇中每个mention对应的角色序列
    def _load_transcripts(self):
        # 开始计时
        self.timer.start("load_transcript")
        # 读取《老友记》4个季的剧本数据文件名
        data_in = Paths.Transcripts.get_input_transcript_paths()

        # 实例化数据读取对象
        reader = SpliceReader()
        # 初始化说话者集合，词性标记集合，依存标记集合，人名标记集合
        spks, poss, deps, ners = set(), set(), set(), set()
        # 遍历《老友记》每个季的数据，构建训练和验证集
        for d_in in data_in:
            # 读取一个季数据中所有episodes和mentions，d_in[0]存储本季数据文件名
            es, ms = reader.read_season_json(d_in[0])
            # 更新说话者标识集合
            spks.update(TranscriptUtils.collect_speakers(es))
            # 更新词性标识集合
            poss.update(TranscriptUtils.collect_pos_tags(es))
            # 更新人名标识集合
            ners.update(TranscriptUtils.collect_ner_tags(es))
            # 更新依存标记集合
            deps.update(TranscriptUtils.collect_dep_labels(es))
            # keys存储训练训练和验证和测试中的mentions组id，1个mention组含有1个场景中的所有mention
            # 训练d_trn、验证d_dev字典的存储结构为 <mentsion组id, [mention1, mention2, ...]>
            keys, d_trn, d_dev = set(), dict(), dict()

            # 遍历1个季的剧本语料中的每个mention，构建训练和验证集字典，构建mention组id集合
            for m in ms:
                # 当前mention所在的剧集id
                eid = m.tokens[0].parent_episode().id
                # 当前mention所在场景的id
                sid = m.tokens[0].parent_scene().id

                # 根据剧集id的值，决定target指向训练集字典或验证集字典
                # 每个季的数据中的1-19集中的所有mention作为训练集
                # 每个季的数据中的20集以后剧集中的所有mention作为验证集
                if eid in d_in[1]:
                    target = d_trn
                elif eid in d_in[2]:
                    target = d_dev
                else:
                    continue

                    # 计算mention组id，同一集同一场景中的mention共享同一个mention组id
                key = eid * 100 + sid
                # 将mention添加到训练集字典或验证集字典
                if key not in target:
                    target[key] = []
                target[key].append(m)
                # 记录mentions组id
                keys.add(key)

            # 按照mention组id排序所有mention组，并遍历每个mention组，
            # 构建训练集trn_coref_states，验证集dev_coref_states
            for key in sorted(keys):
                if key in d_trn:
                    # 针对每一个场景构建1个共指簇PluralCorefState实例
                    self.trn_coref_states.append(PluralCorefState(d_trn[key], extract_gold=True))
                if key in d_dev:
                    self.dev_coref_states.append(PluralCorefState(d_dev[key], extract_gold=True))
            # 1个季的数据读取完毕，记录读取到的mention数量
            self.coref_logger.info("Transcript loaded: %s, %d mentions" % (d_in[0], len(ms)))

        # 读取《我爱我家》数据，构建测试集
        # 数据集路径
        data_in = [("data/enhanced-jsons_wawj/wawj_season_01.json",)]
        # 遍历《我爱我家》每个季的数据，构建测试集
        for d_in in data_in:
            # 读取一个季数据中所有episodes和mentions，d_in[0]存储本季数据文件名
            es, ms = reader.read_season_json(d_in[0])
            # 测试d_tst字典的存储结构为 < mentsion组id, [mention1, mention2, ...] >
            keys, d_tst = set(), dict()
            # 遍历1个季的剧本语料中的每个mention，构建测试集字典，构建mention组id集合
            for m in ms:
                # 当前mention所在的剧集id
                eid = m.tokens[0].parent_episode().id
                # 当前mention所在场景的id
                sid = m.tokens[0].parent_scene().id

                # target指向测试集字典
                target = d_tst
                # 计算mention组id，同一集同一场景中的mention共享同一个mention组id
                key = eid * 100 + sid

                # 计算mention组id，同一集同一场景中的mention共享同一个mention组id
                key = eid * 100 + sid
                # 将mention添加到训练集字典或验证集字典
                if key not in target:
                    target[key] = []
                target[key].append(m)
                # 记录mentions组id
                keys.add(key)

            # 按照mention组id排序所有mention组，并遍历每个mention组，
            # 构建训练集trn_coref_states，验证集dev_coref_states
            for key in sorted(keys):
                if key in d_tst:
                    # 针对每一个场景构建1个共指簇PluralCorefState实例
                    self.tst_coref_states.append(PluralCorefState(d_tst[key], extract_gold=True))

            # 1个季的数据读取完毕，记录读取到的mention数量
            self.coref_logger.info("wawj Transcript loaded: %s w/ %d mentions" % (d_in[0], len(ms)))

        # 训练集XXX数量
        trnc = sum(map(len, self.trn_coref_states))
        # 验证集XXX数量
        devc = sum(map(len, self.dev_coref_states))
        # 测试集XXX数量
        tstc = sum(map(len, self.tst_coref_states))

        # 输出读取到的数据信息到日志文件
        self.coref_logger.info(
            "%d transcript(s) loaded with %d speakers and %d mentions (Trn/Dev/Tst: %d(%d)/%d(%d)/%d(%d)) - %.2fs\n"
            % (
                len(data_in),
                len(spks),
                trnc + devc + tstc,
                len(self.trn_coref_states),
                trnc,
                len(self.dev_coref_states),
                devc,
                len(self.tst_coref_states),
                tstc,
                self.timer.end("load_transcript")
            )
        )

        return spks, poss, deps, ners

    # 抽取共指消解特征，训练共指消解模型，保存共指消解模型，
    # 如果设置seed_path="test"，则只抽取共指消解特征，不训练也不保存共指消解模型。
    def run_coref(self, seed_path=""):
        # 加载角色识别语料
        spks, poss, deps, ners = self._load_transcripts()

        # 抽取共指特征，save_feats=False不保存抽取出的特征
        self._extract_coref_features(spks, poss, ners, deps, save_feats=False)

        # 初始化other类型mention和general类型mention
        eftdims, mftdim, pftdim = self._get_coref_feature_shapes()
        init_super_mentions(eftdims, mftdim, pftdim)

        # 搭建共指消解模型
        model = NoClusterFeatsPluralACNN(eftdims,
                                         mftdim,
                                         pftdim,
                                         self.coref_params["number_of_filters"],
                                         self.coref_params["gpu_number"],
                                         self.coref_logger,
                                         gpu=self.coref_params["gpu_settings"])

        if type(seed_path) == str and len(seed_path) == 0:
            # 训练共指消解模型并自动保存
            model.train_ranking(self.trn_coref_states,
                                self.dev_coref_states,
                                nb_epoch=self.coref_params["number_of_epochs"],
                                batch_size=self.coref_params["batch_size"],
                                model_out=self.coref_model_save_path)
        else:
            # 加载共指消解模型
            model.load_model_weights(self.coref_model_save_path)

        # 共指消解模型评测
        self.coref_logger.info('\nEvaluating trained model on Tst')
        model.decode_clusters([s.reset() for s in self.tst_coref_states])

        for s in self.tst_coref_states:
            s.create_singletons()

        # golds测试语料中标注好的共指簇，autos为系统预测的共指簇
        golds, autos, = [s.gCs for s in self.tst_coref_states], [s.auto_clusters() for s in self.tst_coref_states]
        # B3评测方法
        p, r, f = BCubeEvaluator().evaluate_documents(golds, autos)
        self.coref_logger.info('Bcube - %.4f/%.4f/%.4f' % (p, r, f))
        # Ceaf评测方法
        p, r, f = CeafeEvaluator().evaluate_documents(golds, autos)
        self.coref_logger.info('Ceafe - %.4f/%.4f/%.4f' % (p, r, f))
        # Blanc评测方法
        p, r, f = BlancEvaluator().evaluate_documents(golds, autos)
        self.coref_logger.info('Blanc - %.4f/%.4f/%.4f' % (p, r, f))


    # 加载共指消解模型，并解析出共指消解特征
    def extract_learned_coref_features(self):
        # 获取共指消解特征各向量维度
        eftdims, mftdim, pftdim = self._get_coref_feature_shapes()
        # 实例化共指消解模型
        model = NoClusterFeatsPluralACNN(eftdims,
                                         mftdim,
                                         pftdim,
                                         self.coref_params["number_of_filters"],
                                         self.coref_params["gpu_number"],
                                         self.export_clusters_logger,
                                         gpu=self.coref_params["gpu_settings"])
        # 加载共指消解模型
        model.load_model_weights(self.coref_model_save_path)

        # 解析出共指消解特征
        all_states = sum([self.trn_coref_states, self.dev_coref_states, self.tst_coref_states], [])
        ms = sum(all_states, [])
        m_efts = np.array([m.feat_map['efts'] for m in ms])
        m_mfts = np.array([m.feat_map['mft'] for m in ms])
        m_efts = [np.stack(m_efts[:, g]) for g in range(len(m_efts[0]))]

        for m, r in zip(ms, model.get_mreprs(m_efts + [m_mfts])):
            m.feat_map['mrepr'] = r

        for s in all_states:
            pairs, s.mpairs = [], {m: dict() for m in s}
            m1_efts, m2_efts, m1_mfts, m2_mfts, mp_pfts = [[] for _ in range(4)], [[] for _ in range(4)], [], [], []

            if len(s) > 1:
                for i, cm in enumerate(s[1:], 1):
                    cefts, cmft = cm.feat_map['efts'], cm.feat_map['mft']
                    for am in s[:i]:
                        pefts, pmft, pft = am.feat_map['efts'], am.feat_map['mft'], s.pfts[am][cm]

                        for l, e in zip(m1_efts + m2_efts + [m1_mfts, m2_mfts, mp_pfts],
                                        pefts + cefts + [pmft, cmft, pft]):
                            l.append(e)

                        pairs.append((am, cm))

                m1_efts, m2_efts, m1_mfts, m2_mfts, mp_pfts = [np.array(g) for g in m1_efts], \
                                                              [np.array(g) for g in m2_efts], \
                                                              np.array(m1_mfts), \
                                                              np.array(m2_mfts), \
                                                              np.array(mp_pfts)

                mpairs = model.get_mpairs(m1_efts + m2_efts + [m1_mfts, m2_mfts, mp_pfts])
                for mp, (am, cm) in zip(mpairs, pairs):
                    s.mpairs[am][cm] = mp

    def run_entity_linking(self, seed_path=""):
        self.entity_linking_logger.info("Beginning joint entity linker...")
        self.entity_linking_logger.info("-" * 40)
        self._run_joint_linking(seed_path)

    # 实体关系抽取
    def _run_joint_linking(self, seed_path=""):
        all_states = sum([self.trn_coref_states, self.dev_coref_states, self.tst_coref_states], [])

        for m in sum(all_states, []):
            m.gold_refs = [self.other_label
                           if gref.lower() not in self.linking_labels
                           else gref.lower()
                           for gref in m.gold_refs]

        m1, m2 = self.trn_coref_states[0][0], self.trn_coref_states[0][1]
        mrepr_dim = len(m1.feat_map['mrepr'])
        mpair_dim = len(self.trn_coref_states[0].mpairs[m1][m2])

        # 构建JointMentionClusterEntityLinker实例
        model = JointMentionClusterEntityLinker(self.linking_params["number_of_filters"],
                                                mrepr_dim,
                                                mpair_dim,
                                                self.linking_labels,
                                                self.entity_linking_logger,
                                                gpu=self.linking_params["gpu_settings"])

        if type(seed_path) == str and len(seed_path) == 0:  # 训练
            model.train_linking(self.trn_coref_states,  # 训练集共指特征
                                self.dev_coref_states,  # 验证集共指特征
                                nb_epoch=self.linking_params["number_of_epochs"],  # 训练集使用周期数
                                batch_size=self.linking_params["batch_size"],  # 每一批次数据大小
                                model_out=self.linking_model_save_path)
        else:
            model.load_model_weights(self.linking_model_save_path + ".sing",
                                     self.linking_model_save_path + ".pl")

        # 评测
        self.entity_linking_logger.info('\nEvaluating trained model')

        # 调用模型的metric方法，输出准确率
        sacc, pacc = model.accuracy(self.tst_coref_states)
        self.entity_linking_logger.info('Test accuracy: sacc=%.4f/pacc=%.4f\n' % (sacc, pacc))

        # 预测测试集中每个代词对应的角色
        model.do_linking(self.tst_coref_states)
        # 针对每一个角色，统计gold中的代词与预测出的代词之间的重复数量，计算准确率、召回率、F值
        scorer = LinkingMicroF1Evaluator(self.linking_labels)
        scores = scorer.evaluate_states(self.tst_coref_states)
        # 计算平均角色准确率
        avg = np.mean(list(scores.values()), axis=0)
        # 输出每个角色的准确率、召回率、F值
        for l, s in scores.items():
            self.entity_linking_logger.info("%10s : %.4f %.4f %.4f" % (l, s[0], s[1], s[2]))
        self.entity_linking_logger.info('\n%10s : %.4f %.4f %.4f' % ('avg', avg[0], avg[1], avg[2]))

        # 计算并输出宏平均准确率、召回率、f值
        macro_scorer = LinkingMacroF1Evaluator()
        p, r, f = macro_scorer.evaluate_states(self.tst_coref_states)
        self.entity_linking_logger.info("\n%10s : %.4f %.4f %.4f" % ("macro", p, r, f))

        # 输出标注结果
        results_path = Paths.Logs.get_log_dir() + \
                       to_dir_name(Paths.Logs.get_iteration_dir_name(self.iteration_num))
        if not os.path.exists(results_path):
            os.mkdir(results_path)
            print("create %s" % results_path)
        results_file = "joint-linking-results.txt"
        writer = StateWriter()
        writer.open_file(results_path + results_file)
        writer.write_states(self.tst_coref_states)

    def _run_baseline_linking(self):
        all_states = sum([self.trn_coref_states, self.dev_coref_states, self.tst_coref_states], [])

        for m in sum(all_states, []):
            m.gold_refs = [self.other_label
                           if gref.lower() not in self.linking_labels
                           else gref.lower()
                           for gref in m.gold_refs]

        m1, m2 = self.trn_coref_states[0][0], self.trn_coref_states[0][1]
        mrepr_dim = len(m1.feat_map['mrepr'])
        mpair_dim = len(self.trn_coref_states[0].mpairs[m1][m2])

        model = MentionClusterEntityLinker(self.linking_params["number_of_filters"],
                                           mrepr_dim,
                                           mpair_dim,
                                           self.linking_labels,
                                           self.entity_linking_logger,
                                           gpu=self.linking_params["gpu_settings"])

        model.train_linking(self.trn_coref_states,
                            self.dev_coref_states,
                            nb_epoch=self.linking_params["number_of_epochs"],
                            batch_size=self.linking_params["batch_size"],
                            model_out="")

        self.entity_linking_logger.info('\nEvaluating trained model')
        scorer = LinkingMicroF1Evaluator(self.linking_labels)
        model.do_linking(self.tst_coref_states)
        scores = scorer.evaluate_states(self.tst_coref_states)
        avg = np.mean(list(scores.values()), axis=0)

        self.entity_linking_logger.info('Test accuracy: %.4f\n' % model.accuracy(self.tst_coref_states))
        for l, s in scores.items():
            self.entity_linking_logger.info("%10s : %.4f %.4f %.4f" % (l, s[0], s[1], s[2]))
        self.entity_linking_logger.info('\n%10s : %.4f %.4f %.4f' % ('avg', avg[0], avg[1], avg[2]))

        macro_scorer = LinkingMacroF1Evaluator()
        p, r, f = macro_scorer.evaluate_states(self.tst_coref_states)
        self.entity_linking_logger.info("\n%10s : %.4f %.4f %.4f" % ("macro", p, r, f))

        results_file = "baseline-linking-results.txt"
        results_path = Paths.Logs.get_log_dir() + \
            to_dir_name(Paths.Logs.get_iteration_dir_name(self.iteration_num)) + \
            results_file

        writer = StateWriter()
        writer.open_file(results_path)
        writer.write_states(self.tst_coref_states)

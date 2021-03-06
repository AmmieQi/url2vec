__author__ = 'chris'

import numpy as np
from itertools import tee

from sklearn import metrics
from hdbscan import HDBSCAN
from sklearn import preprocessing
from sklearn.manifold import TSNE
from sklearn.cluster import KMeans
from gensim.models import Word2Vec

from url2vec.util.plotter import scatter_plot
from url2vec.util.seqmanager import get_color
from nltk.stem.snowball import SnowballStemmer
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

class Url2Vec:

    # Constructor
    def __init__(self,
        use_embedding=True, sg=0, min_count=1, window=10, negative=5, size=100, normalize=True,
        use_text=True, max_df=0.9, max_features=200000, min_df=0.05, dim_red=100, tfidf=True, svd=True):
        # embedding params
        self.use_embedding = use_embedding
        self.sg            = sg
        self.min_count     = min_count
        self.window        = window
        self.negative      = negative
        self.size          = size
        self.normalize     = normalize
        # text params
        self.use_text     = use_text
        self.max_df       = max_df
        self.max_features = max_features
        self.min_df       = min_df
        self.dim_red      = dim_red
        self.tfidf        = tfidf
        self.svd          = svd

    # matching matrix
    def __get_confusion_table(self, ground_truth, predicted_labels):
        assert len(ground_truth) == len(predicted_labels), "Invalid input arguments"
        assert len(ground_truth) > 0, "Invalid input arguments"
        assert isinstance(ground_truth[0], int), "Type is not int"
        assert isinstance(predicted_labels[0], int), "Type is not int"

        # matrix -> ground_truth x predicted_labels
        conf_table = np.zeros((len(set(ground_truth)), len(set(predicted_labels))))
        real_clust = list(set(ground_truth))
        # it's necessary because ground truth can have discontinuous cluster set
        clust_to_index = {real_clust[i]: i for i in range(len(real_clust))}

        for real_clust in clust_to_index.values():
            for i in range(len(predicted_labels)):
                if clust_to_index[ground_truth[i]] == real_clust:
                    cluster_found = predicted_labels[i]
                    conf_table[real_clust, cluster_found] = conf_table[real_clust, cluster_found] + 1
        return conf_table


    # trains word2vec with the given parameters and returns vectors for each page
    def __word_embedding(self, sequences):
        word2vec = Word2Vec(
            sg        = self.sg,
            min_count = self.min_count,
            window    = self.window,
            negative  = self.negative,
            size      = self.size
        )
        build_seq, train_seq = tee(sequences)
        word2vec.build_vocab(build_seq)
        word2vec.train(train_seq)
        return {url: word2vec[url] for url in word2vec.vocab}


    # returns tfidf vector for each page
    # documents must be a map
    def __vsm(self, documents, sep=" "):
        tokenize = lambda text: text.split(sep)
        stem = lambda token, stemmer=SnowballStemmer("english"): stemmer.stem(token)
        tokenize_and_stem = lambda text: [stem(token) for token in tokenize(text)]
        urls  = documents.keys()
        texts = documents.values()
        tfidf_vectorizer = TfidfVectorizer(
            max_df       = self.max_df,
            max_features = self.max_features,
            min_df       = self.min_df,
            stop_words   = 'english',
            use_idf      = self.tfidf,
            tokenizer    = tokenize_and_stem,
            ngram_range  = (1, 2)
        )
        # dt_dense = svd.fit_transform(dt_matrix) if self.svd else dt_matrix.todense().tolist()
        dt_matrix = tfidf_vectorizer.fit_transform(texts)
        if self.svd:
            svd = TruncatedSVD(n_components=self.dim_red, algorithm="arpack", random_state=1)
            dt_matrix = svd.fit_transform(dt_matrix)
        else:
            dt_matrix = dt_matrix.todense().tolist()
        return {urls[i]: dt_matrix[i] for i in range(len(urls))}


    # calls the chosen algorithm with the data builded from the input arguments
    # documents passed must be a map, to join the embedding to the proper tf-idf vector
    def fit_predict(self, algorithm=HDBSCAN(min_cluster_size=7), walks=None, documents=None):
        empty_map = { url: [] for url in documents }
        embedding_vecs = self.__word_embedding(walks) if self.use_embedding else empty_map
        pages_vecs     = self.__vsm(documents) if self.use_text else empty_map

        # normalize embedding vecs with min-max scaler
        # embedding_vecs is a damned dictionary
        if self.normalize:
            values = embedding_vecs.values()
            keys   = embedding_vecs.keys()
            min_max_scaler = preprocessing.MinMaxScaler()
            values_scaled  = min_max_scaler.fit_transform(values)
            embedding_vecs = {keys[i]: values_scaled[i] for i in range(len(keys))}

        self.urls     = embedding_vecs.keys() if self.use_embedding else documents.keys()
        self.training = [np.append(embedding_vecs[url], pages_vecs[url]) for url in self.urls]
        self.labels_  = algorithm.fit_predict(self.training)
        self.labels_  = [int(x) for x in self.labels_]
        return self.labels_


    # needs the real membership (ground truth) and the membership returned by the algorithm (pred_membership)
    # ...(already given if the fit_predict was successful)
    # returns the confusion matrix
    def test(self, ground_truth, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No train, No test !"
        pred_membership = self.labels_ if pred_membership is None else pred_membership
        self.ground_truth = ground_truth

        return self.__get_confusion_table(ground_truth, pred_membership)

    # homogeneity score
    def homogeneity_score(self, ground_truth=None, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (ground_truth is not None or self.ground_truth is not None), "Ground Truth not given"

        pred_membership = self.labels_ if pred_membership is None else pred_membership
        ground_truth = self.ground_truth if ground_truth is None else ground_truth

        return metrics.homogeneity_score(ground_truth, pred_membership)

    # completeness score
    def completeness_score(self, ground_truth=None, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (ground_truth is not None or self.ground_truth is not None), "Ground Truth not given"

        pred_membership = self.labels_ if pred_membership is None else pred_membership
        ground_truth = self.ground_truth if ground_truth is None else ground_truth

        return metrics.completeness_score(ground_truth, pred_membership)

    # v-measure score
    def v_measure_score(self, ground_truth=None, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (ground_truth is not None or self.ground_truth is not None), "Ground Truth not given"

        pred_membership = self.labels_ if pred_membership is None else pred_membership
        ground_truth = self.ground_truth if ground_truth is None else ground_truth

        return metrics.v_measure_score(ground_truth, pred_membership)

    # adjusted rand score
    def adjusted_rand_score(self, ground_truth=None, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (ground_truth is not None or self.ground_truth is not None), "Ground Truth not given"

        pred_membership = self.labels_ if pred_membership is None else pred_membership
        ground_truth = self.ground_truth if ground_truth is None else ground_truth

        return metrics.adjusted_rand_score(ground_truth, pred_membership)

    # adjusted mutual information
    def adjusted_mutual_info_score(self, ground_truth=None, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (ground_truth is not None or self.ground_truth is not None), "Ground Truth not given"

        pred_membership = self.labels_ if pred_membership is None else pred_membership
        ground_truth = self.ground_truth if ground_truth is None else ground_truth

        return metrics.adjusted_mutual_info_score(ground_truth, pred_membership)

    # silhouette score
    def silhouette_score(self, pred_membership=None):
        assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"
        assert (self.training is not None), "No training yet !"

        pred_membership = self.labels_ if pred_membership is None else pred_membership

        return metrics.silhouette_score(np.array(self.training), np.array(pred_membership), metric='euclidean')

    # uses t-SNE for dimensionality redustion
    def two_dim(self, high_dim_vecs=None):
        assert (high_dim_vecs is not None or self.training is not None), "No prediction yet !"
        high_dim_vecs = self.training if high_dim_vecs is None else high_dim_vecs
        tsne = TSNE(n_components=2)

        self.twodim = tsne.fit_transform(high_dim_vecs)

        return self.twodim

    # plots data
    def plot_trace(self, twodim=None, urls=None, pred_membership=None, user="chrispolo", api_key="89nned6csl"):
        # assert (twodim is not None or self.twodim is not None), "No twodim vectors !"
        # assert (urls is not None or self.urls is not None), "No urls !"
        # assert (pred_membership is not None or self.labels_ is not None), "No prediction yet !"

        twodim = self.two_dim(high_dim_vecs=self.training) if twodim is None else twodim
        urls = self.urls if urls is None else urls
        pred_membership = self.labels_ if pred_membership is None else pred_membership

        return scatter_plot(twodim, urls, [get_color(clust) for clust in pred_membership], user, api_key)

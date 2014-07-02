import numpy as np
import collections as co
import igraph as ig
import operator
import itertools
import argparse

from circulo.algorithms import overlap

from time import sleep

# Possible optimizations and notes:
#   * Calculating the pair betweennesses is the large bottleneck.
#       * However, calculation of all-pairs-shortest-paths
#          and pair betweennesses are highly parallelizable.
#   * Keep a record of splits or merges?
#       * Right now, we store a lot of redundant information with a new
#           VertexCover item for every split.





def conga(OG, calculate_modularities=None, optimal_count=None):
    """
    Defines the CONGA algorithm outlined in the Gregory 2007 paper
    (An Algorithm to Find Overlapping Community Structure in Networks)

    Returns a CrispOverlap object of all of the covers.
    """

    G = OG.copy()

    comm = G.components()

    # Just in case the original graph is disconnected
    nClusters = len(comm)

    # Store the original ids of all vertices
    G.vs['CONGA_orig'] = [i.index for i in OG.vs]

    # Initialize the modDict with the modularity of the original graph
    if calculate_modularities is None:
        modDict = {nClusters: G.modularity(comm.membership)}
    else: modDict = None
    allCovers = {nClusters : ig.VertexCover(OG)}
    while G.es:
        split = remove_edge_or_split_vertex(G)
        if split:
            comm = G.components().membership
            cover = get_cover(G, OG, comm)
            nClusters += 1
            # short circuit stuff would go here.
            allCovers[nClusters] = cover
            if calculate_modularities is None:
                modDict[nClusters] = G.modularity(comm)
    if calculate_modularities is None: calculate_modularities = "lazar"
    return overlap.CrispOverlap(OG, allCovers,
                                    modularities=modDict,
                                    modularity_measure=calculate_modularities,
                                    optimal_count=optimal_count)


def remove_edge_or_split_vertex(G):
    """
    The heart of the CONGA algorithm. Decides which edge should be
    removed or which vertex should be split. Returns True if the
    modification split the graph.
    """
    # has the graph split this iteration?
    split = False
    eb = G.edge_betweenness()

    maxIndex, maxEb = max(enumerate(eb), key=operator.itemgetter(1))
    # We might be able to calculate vertex betweenness and edge
    # betweenness at the same time. Not a bottleneck, though.
    vb = G.betweenness()

    # Only consider vertices with vertex betweenness >= max
    # edge betweenness. From Gregory 2007 step 3
    vi = [i for i, b in enumerate(vb) if b >= maxEb]

    edge = G.es[maxIndex].tuple

    if not vi:
        split = delete_edge(G, edge)
    else:
        pb = pair_betweenness(G, vi)
        maxSplit, vNum, splitInstructions = max_split_betweenness(G, pb)
        if maxSplit > maxEb:
            split = split_vertex(G, vNum, splitInstructions[0])
        else:
            split = delete_edge(G, edge)
    return split


def get_cover(G, OG, comm):
    """
    Given the graph, the original graph, and a community
    membership list, returns a vertex cover of the communities
    referring back to the original community.
    """
    coverDict = co.defaultdict(list)
    for i, community in enumerate(comm):
        coverDict[community].append(int(G.vs[i]['CONGA_orig']))
    return ig.clustering.VertexCover(OG, clusters=coverDict.values())


def delete_edge(G, edge):
    """
    Given a graph G and one of its edges in tuple form, checks if the deletion
    splits the graph.
    """
    G.delete_edges(edge)
    return check_for_split(G, edge)


def check_for_split(G, edge):
    """
    Given an edge in tuple form, check if it splits the
    graph into two disjoint clusters. If so, it returns
    True. Otherwise, False.
    """
    # Possibly keep a record of splits.
    return not G.edge_disjoint_paths(source=edge[0], target=edge[1])


def split_vertex(G, v, splitInstructions):
    """
    Splits the vertex v into two new vertices, each with
    edges depending on s. Returns True if the split
    divided the graph, else False.
    """
    new_index = G.vcount()
    G.add_vertex()
 #   G.vs[new_index]['label'] = G.vs[v]['label']
    G.vs[new_index]['CONGA_orig'] = G.vs[v]['CONGA_orig']

    # adding all relevant edges to new vertex, deleting from old one.
    for partner in splitInstructions:
        G.add_edge(new_index, partner)
        G.delete_edges((v, partner))

    # check if the two new vertices are disconnected.
    return check_for_split(G, (v, new_index))


def get_triplets(a, n):
    """
    Given a list a, yields all sublists of length 3.
    """
    # Currently unused, but left in to show purpose of while
    # loop in pair_betweenness.
    back = 3
    while back <= n:
        yield a[back-3:back]
        back += 1


def pair_betweenness(G, arr):
    """
    Returns a dictionary of the pair betweenness of all vertices in arr.

    The structure of the returned dictionary is dic[v][(u, w)] = c, where c
    is the number of shortest paths traverse through u, v, w.
    """
    dic = {vertex : {uw : 0 for uw in itertools.permutations(G.neighbors(vertex), 2)} for vertex in arr}

    # To count the pair betweennesses, we find all of the shortest paths and consider all
    # sub-arrays of length 3. Anytime a u, v, w triplet appears, we add one to dic[v][(u, w)].

    allPairsShortestPaths = []
    for vertex in G.vs:
        allPairsShortestPaths += G.get_all_shortest_paths(vertex) # flow`

    seen = set()
    for path in allPairsShortestPaths:
        # u -> -> v == v -> -> u for shortest paths, we only need to examine one.
        if (path[0], path[-1]) not in seen:
            seen.add((path[-1], path[0]))
            n = len(path)
            # The next 6 lines are just a faster implementation of get_triplets above.
            back = 3
            while back <= n:
                if path[back - 2] in dic:
                    # Add path to dict in both directions.
                    dic[path[back-2]][(path[back - 3], path[back - 1])] += 2
                    dic[path[back-2]][(path[back - 1], path[back - 3])] += 2
                back += 1

    return dic


def create_clique(G, v, pb):
    """
    Given a vertex and its pair betweennesses, returns a k-clique
    representing all of its neighbors, with edge weights determined by the pair
    betweenness scores. Algorithm discussed on page 5 of the CONGA paper.
    """
    neighbors = G.neighbors(v)

    # map each neighbor to its index in the adjacency matrix
    mapping = {neigh : i for i, neigh in enumerate(neighbors)}
    n = len(neighbors)

    # Can use ints instead: (dtype=int). Only works if we use matrix_min
    # instead of mat_min.
    clique = np.matrix(np.zeros((n, n)))

    for uw, score in pb.items():
        clique[mapping[uw[0]], mapping[uw[1]]] = score

    # Ignore any self loops if they're there. If not, this line
    # does nothing and can be removed.
    np.fill_diagonal(clique, 0)
    return clique


def max_split_betweenness(G, dic):
    """
    Given a dictionary of vertices and their pair betweenness scores, uses the greedy
    algorithm discussed in the CONGA paper to find a (hopefully) near-optimal split.

    Returns a 3-tuple (vMax, vNum, vSpl) where vMax is the max split betweenness,
    vNum is the vertex with said split betweenness, and vSpl is a list of which
    vertices are on each side of the optimal split.
    """
    vMax = 0
    # for every vertex of interest, we want to figure out the maximum score achievable
    # by splitting the vertices in various ways, and return that optimal split
    for v in dic:
        clique = create_clique(G, v,dic[v])

        # initialize a list on how we will map the neighbors to the collapsing matrix
        vMap = [[ve] for ve in G.neighbors(v)]

        # we want to keep collapsing the matrix until we have a 2x2 matrix and its
        # score. Then we want to remove index j from our vMap list and concatenate
        # it with the vMap[i]. This begins building a way of keeping track of how
        # we are splitting the vertex and its neighbors
        while clique.size > 4:
            i,j,clique = reduce_matrix(clique)
            vMap[i] += vMap.pop(j)

        if clique[0,1] > vMax:
            vMax = clique[0,1]
            vNum = v
            vSpl = vMap
    return vMax,vNum,vSpl


def matrix_min(mat):
    """
    Given a symmetric matrix, find an index of the minimum value
    in the upper triangle (not including the diagonal.)
    """
    # Currently, this function is unused, as its result is
    # the same as that of mat_min, and it is not always
    # faster. Left in for reference in case mat_min becomes
    # a bottleneck.

    # find the minimum from the upper triangular matrix
    # (not including the diagonal)
    upperTri = np.triu_indices(mat.shape[0], 1)
    minDex = mat[upperTri].argmin()

    # find the index in the big matrix. TODO: do so
    # with some algebra.
    triN = mat.shape[0] - 1
    row = 0
    while minDex >= triN:
        minDex -= triN
        triN -= 1
        row += 1
    col = mat.shape[0] - triN + minDex
    return row, col


def mat_min(M):
    """
    Given a matrix, find an index of the minimum value (not including the
    diagonal).
    """
    # take a matrix we pass in, and fill the diagonal with the matrix max. This is
    # so that we don't grab any values from the diag.
    np.fill_diagonal(M, float('inf'))

    # figure out the indices of the cell with the lowest value.
    i,j = np.unravel_index(M.argmin(), M.shape)
    np.fill_diagonal(M,0)
    return i, j


def reduce_matrix(M):
    """
    Given a matrix M, collapses the row and column of the minimum value. This is just
    an adjacency matrix way of implementing the greedy "collapse" discussed in CONGA.

    Returns the new matrix and the collapsed indices.
    """
    i,j = mat_min(M)
    #i, j = matrix_min(M)
    # add the ith row to the jth row and overwrite the ith row with those values
    M[i,:] = M[j,:] + M[i,:]

    # delete the jth row
    M = np.delete(M, (j), axis=0)

    # similarly with the columns
    M[:,i] = M[:,j] + M[:,i]
    M = np.delete(M, (j), axis=1)
    np.fill_diagonal(M,0) # not sure necessary.
    return i,j,M


def pretty_print_cover(G, cover, label='CONGA_index'):
    """
    Takes a cover in vertex-id form and prints it nicely
    using label as each vertex's name.

    TODO introduced a bug here too :(
    """
    #if label == 'CONGA_index':
    pp = [G.vs[num] for num in [cluster for cluster in cover]]
    #else:
    #    pp = [G.vs[num][label] for num in [cluster for cluster in cover]]
    for count, comm in enumerate(pp):
        print("Community {0}:".format(count))
        for v in comm:
            print("\t"),
            if label == 'CONGA_index':
                print(v.index)
            else:
                print(v[label])
        print


def run_demo():
    """
    Finds the communities of the Zachary graph and gets the optimal one using
    Lazar's measure of modularity. Finally, pretty-prints the optimal cover.
    """
    G = ig.Graph().Famous("Zachary")
    result = CONGA(G, calculate_modularities="lazar")
    pretty_print_cover(G, result.as_cover(), label='CONGA_index')


def main():
    parser = argparse.ArgumentParser(description="""Run CONGA from the command line. Mostly meant as a demo -- only prints one cover.""")
    parser.add_argument('-m', '--modularity_measure', choices=['lazar'],
                   help="""Calculate the modularities using the specified
                            modularity measure. Currently only supports lazar.""")
    parser.add_argument('-n', '--num_clusters', type=int, help="""Specify the number of clusters to use.""")
    parser.add_argument('-d', '--demo', action='store_true', help="""Run a demo with the famous Zachary's Karate Club data set. Overrides all other options.""")
    parser.add_argument('-l', '--label', default='CONGA_index', nargs='?', const='label', help="""Choose which attribute of the graph to print.
                            When this option is present with no parameters, defaults to 'label'. When the option is not
                            present, defaults to the index.""")
    parser.add_argument('file', nargs='?', help="""The path to the file in igraph readable format.""")
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return
    if not args.file:
        print("CONGA.py: error: no file specified.\n")
        print(parser.parse_args('-h'.split()))
        return
    G = ig.read(args.file)
    result = CONGA(G, calculate_modularities=args.modularity_measure, optimal_count=args.num_clusters)
    pretty_print_cover(G, result.as_cover(), label=args.label)


if __name__ == "__main__":
    main()


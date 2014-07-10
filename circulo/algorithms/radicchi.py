import sys
import igraph as ig
import itertools

def radicchi(G):
    """
    Uses the Radicchi et al. algorithm to find the communities in a graph. Returns a list of the splits in the graph.
    """
    g = G.copy()

    g.vs['id'] = list(range(g.vcount()))

    # Caching some global graph information and updating it manually. Because igraph
    # tends to recalculate this stuff on the whole graph every time, 
    # storing it and manipulating only the parts that change will make things faster.
    degree = g.degree()
    neighbors = [set(g.neighbors(v)) for v in g.vs]
    edges = {e.tuple for e in g.es}

    communities = set()

    while len(edges) > 0:
        min_edge = None; min_ecc = None
        for edge in edges:
            ecc = edge_clustering_coefficient(edge[0], edge[1], degree, neighbors)
            if not min_edge or ecc < min_ecc:
                min_edge = edge
                min_ecc = ecc

        g.delete_edges(min_edge); edges.discard(min_edge)
        u, v = min_edge
        neighbors[u].discard(v); neighbors[v].discard(u)
        degree[u] -= 1; degree[v] -= 1
        
        if g.edge_connectivity(source=u, target=v) == 0:
            result = prune_components(G, g, community_measure='weak')
            if result['pruned']:
                communities = result['communities']
                remaining = result['remaining']
                g = g.subgraph(remaining)
                degree = g.degree()
                neighbors = [set(g.neighbors(v)) for v in g.vs]
                edges = {e.tuple for e in g.es}

    return communities

def prune_components(orig, new, community_measure='strong'):
    components = new.components()
    ids = new.vs['id']

    new_components = [c for c in components]
    orig_components = [[ids[v] for v in component] for component in new_components]

    is_community = is_strong_community if (community_measure=='strong') else is_weak_community
    community_indices = [i for i, component in enumerate(orig_components) if is_community(orig, component)]

    orig_communities = [orig_components[i] for i in community_indices]
    new_communities = [new_components[i] for i in community_indices]

    result_pruned = False
    result_remaining_nodes = None
    result_orig_communities = None
    if len(community_indices) > 1:
        all_new_community_nodes = sum(new_communities, [])
        all_new_nodes = range(new.vcount())
        all_new_remaining_nodes = list(set(all_new_nodes) - set(all_new_community_nodes))

        result_pruned = True
        result_remaining_nodes = all_new_remaining_nodes
        result_orig_communities = orig_communities

    return {"pruned": result_pruned, "communities": result_orig_communities, "remaining": result_remaining_nodes}

def is_strong_community(G, nodes):
    """
    Checks whether the provided set of nodes form a strong community in the graph G.
    """
    # precondition: nodes must be sorted
    subgraph = G.subgraph(nodes)
    degree = G.degree(nodes)
    community_degree = subgraph.degree()
    for i in range(len(nodes)):
        if community_degree[i] <= (degree[i] - community_degree[i]):
            return False

    return True

def is_weak_community(G, nodes):
    """
    Checks whether the provided set of nodes form a weak community in the graph G.
    """
    # precondition: nodes must be sorted
    subgraph = G.subgraph(nodes)
    degree = G.degree(nodes)
    indegree = subgraph.degree()
    tsum = sum(degree)
    insum = sum(indegree)
    outsum = tsum - insum

    return insum > outsum

def edge_clustering_coefficient(u, v, degree, neighbors):
    """
    Computes the "edge clustering coefficient" of the given edge, defined as the number of triangles
    in which it participates compared to the maximum number of triangles of which it could be a part.
    """
    udeg = degree[u]
    vdeg = degree[v]
    mdeg = min(udeg-1, vdeg-1)
    if mdeg == 0:
        return float('inf')
    else:
        cdeg = len(neighbors[u] & neighbors[v])
        return (cdeg + 1.0) / mdeg

def createDendrogram(G, splits):
   """
   Given a historical list of split edges, creates a dendrogram 
   by calculating the merges. 
 
   Unfortunately, runs in O(n^2). TODO: think about another algorithm
   (perhaps a tree approach?) that does better. This is a useful function
   for any divisive algorithm for which splits can be saved more easily
   than merges.

   Written by Robbie Ostrow (rostrow@iqt.org).
   """
 
   # To create a dendrogram, new merges have id of max id + 1
   n = len(splits) + 1
   merges = []
   while splits:
     # most recent split popped off
     edge = splits.pop()
 
     merges += [edge]
     
     # since we have merged 2 vertices, we have to replace
     # all occurences of those vertices with the new 
     # "merged" index n.
     splits = replaceOccurences(splits, n, edge)
     
     n += 1
 
   return ig.VertexDendrogram(G, merges)

def replaceOccurences(splits, n, edge):
    """
    Given a 2d list `splits`, replaces all occurences of elements in
    `edge` with n.
    """
    for i in range(len(splits)):
            for j in range(2):
                    if splits[i][j] in edge:
                            splits[i][j] = n
    return splits

def main(argv):
    g = ig.Graph.Read_GML('netscience.gml')
    communities = radicchi(g)
    print(communities)
    return communities

if __name__ == "__main__":
    main(sys.argv[1:])
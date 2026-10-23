from difflib import SequenceMatcher
#builds a table where each cell (i,j) holds the closest distance between 2 elements
#as it is in locate_mismatch, where it only uses the name of the tags, it will not work, the approach is to use LLM for semantic matching in <p> levels
# and distance based matching with SequenceMatcher to match on the section level. 
# The flow is then: match a section -> spawn a LLM aligner as a task (co-routine) that aligns on <p> -> if the 2 sections match, mark them as anchor for next section
# anchors are useful when finding out section-split mismatch

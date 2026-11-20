from .reader import read_source, BASE_FIELDS, OPTIONAL_FIELDS
FIELDS=BASE_FIELDS+OPTIONAL_FIELDS
def apply(state):read_source(state,FIELDS,{'编号':'id'})



def test_big_lakes_dont_get_the_small_lake_surface_speedup():
    from wildice.icemodel import surface_speedup
    assert surface_speedup(25) == 4.0
    assert surface_speedup(None) == 4.0
    assert 1.0 < surface_speedup(300) < 4.0
    assert surface_speedup(1427) == 1.0

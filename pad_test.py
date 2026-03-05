def pad_symmetric(txt, blanks_needed, flag_center):
    blank_char = "X"
    if flag_center:
        left_pad = blanks_needed // 2
        right_pad = blanks_needed - left_pad
        padded1 = (blank_char * left_pad) + txt + (blank_char * right_pad)
        
        pad_each = (blanks_needed + 1) // 2
        padded2 = (blank_char * pad_each) + txt + (blank_char * pad_each)
        return padded1, padded2
    else:
        return txt + (blank_char * blanks_needed), ""
        
print("1 blank:", pad_symmetric("abc", 1, True))
print("2 blanks:", pad_symmetric("ab", 2, True))
print("3 blanks:", pad_symmetric("a", 3, True))

from crypto_diligence.tools.keccak import keccak256, selector


def test_keccak256_known_vectors():
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert keccak256(b"abc").hex() == (
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    )


def test_function_selectors_match_the_public_registry():
    assert selector("transfer(address,uint256)") == "a9059cbb"
    assert selector("mint(address,uint256)") == "40c10f19"
    assert selector("pause()") == "8456cb59"
    assert selector("owner()") == "8da5cb5b"
    assert selector("blacklist(address)") == "f9f92be4"
    assert selector("upgradeTo(address)") == "3659cfe6"

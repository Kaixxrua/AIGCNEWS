// Project-local, bounded lossless RSCC filter. Kept free of Godot dependencies
// so the exact inverse can also be exercised by a standalone WASM test.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

static bool meadow_unfilter(uint8_t *dst, const uint8_t *src, size_t size, uint8_t mode) {
	static const uint8_t widths[] = {0, 2, 4, 8, 4, 4, 4, 2};
	static const uint8_t strides[] = {0, 0, 0, 0, 1, 3, 5, 4};
	if (mode >= 8 || size > 1048576 || (size && (!dst || !src))) {
		return false;
	}
	const size_t width = widths[mode];
	if (width == 0) {
		if (size) { std::memcpy(dst, src, size); }
		return true;
	}
	const size_t words = size / width;
	const size_t tail = words * width;
	const size_t stride = strides[mode];
	for (size_t i = 0; i < words; ++i) {
		uint64_t word = 0;
		for (size_t b = 0; b < width; ++b) {
			word |= uint64_t(src[b * words + i]) << (8 * b);
		}
		if (stride && i >= stride) {
			uint64_t previous = 0;
			for (size_t b = 0; b < width; ++b) {
				previous |= uint64_t(dst[(i - stride) * width + b]) << (8 * b);
			}
			word += previous; // Unsigned modulo arithmetic, also for width=8.
		}
		for (size_t b = 0; b < width; ++b) {
			dst[i * width + b] = uint8_t(word >> (8 * b));
		}
	}
	if (size != tail) { std::memcpy(dst + tail, src + tail, size - tail); }
	return true;
}

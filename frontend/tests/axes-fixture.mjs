export function axesFixture(width = 29, height = 29) {
  return { available: true, frame: 'ICRS', unit: 'deg', shape_yx: [height, width], pixel_origin: 0,
    png_y_flipped: true, ra_edge: 'bottom', dec_edge: 'left',
    ra_ticks: [-.5, 0, (width - 1) / 2, width - 1, width - .5].map((pixel, i) => ({ pixel, degrees: [0.02, 0.019, 0, 359.981, 359.98][i] })),
    dec_ticks: [-.5, 0, (height - 1) / 2, height - 1, height - .5].map((pixel, i) => ({ pixel, degrees: [-.02, -.019, 0, .019, .02][i] })) };
}

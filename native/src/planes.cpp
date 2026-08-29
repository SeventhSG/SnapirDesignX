#include "snapir/planes.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace snapir {
namespace {

constexpr double kPi = 3.14159265358979323846;

// Jacobi eigenvalue iteration on a symmetric 3x3. The plane normal is the
// eigenvector of the covariance matrix with the smallest eigenvalue, which is
// the same vector numpy returns as the last row of vt from the SVD of the
// centred cloud. Jacobi is used rather than a closed form because it stays
// accurate when two eigenvalues are close, which happens on a flat ceiling.
void jacobi3(double a[3][3], double eigenvalues[3], double eigenvectors[3][3]) {
  for (int i = 0; i < 3; ++i)
    for (int j = 0; j < 3; ++j) eigenvectors[i][j] = (i == j) ? 1.0 : 0.0;

  for (int sweep = 0; sweep < 64; ++sweep) {
    double off = 0.0;
    for (int i = 0; i < 3; ++i)
      for (int j = i + 1; j < 3; ++j) off += a[i][j] * a[i][j];
    if (off <= 1e-300) break;

    for (int p = 0; p < 3; ++p) {
      for (int q = p + 1; q < 3; ++q) {
        if (std::abs(a[p][q]) <= 1e-300) continue;
        const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
        const double t = (theta >= 0 ? 1.0 : -1.0) /
                         (std::abs(theta) + std::sqrt(theta * theta + 1.0));
        const double c = 1.0 / std::sqrt(t * t + 1.0);
        const double s = t * c;

        for (int k = 0; k < 3; ++k) {
          const double akp = a[k][p], akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (int k = 0; k < 3; ++k) {
          const double apk = a[p][k], aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
        for (int k = 0; k < 3; ++k) {
          const double vkp = eigenvectors[k][p], vkq = eigenvectors[k][q];
          eigenvectors[k][p] = c * vkp - s * vkq;
          eigenvectors[k][q] = s * vkp + c * vkq;
        }
      }
    }
  }
  for (int i = 0; i < 3; ++i) eigenvalues[i] = a[i][i];
}

}  // namespace

double Plane::z_at(double x, double y) const {
  if (std::abs(nz) < 1e-9)
    throw std::runtime_error("plane is vertical; no single Z above (x, y)");
  return pz - (nx * (x - px) + ny * (y - py)) / nz;
}

double Plane::tilt_deg() const {
  return std::acos(std::min(1.0, std::abs(nz))) * 180.0 / kPi;
}

Plane fit_plane(const std::vector<Pt3>& pts) {
  const size_t n = pts.size();
  Plane out;
  if (n == 0) return out;

  double cx = 0, cy = 0, cz = 0;
  for (const auto& p : pts) { cx += p[0]; cy += p[1]; cz += p[2]; }
  cx /= static_cast<double>(n);
  cy /= static_cast<double>(n);
  cz /= static_cast<double>(n);
  out.px = cx; out.py = cy; out.pz = cz;

  // Two points cannot define a plane; fall back to level at the mean height.
  if (n < 3) { out.nx = 0; out.ny = 0; out.nz = 1; return out; }

  double cov[3][3] = {{0, 0, 0}, {0, 0, 0}, {0, 0, 0}};
  for (const auto& p : pts) {
    const double d[3] = {p[0] - cx, p[1] - cy, p[2] - cz};
    for (int i = 0; i < 3; ++i)
      for (int j = 0; j < 3; ++j) cov[i][j] += d[i] * d[j];
  }

  double val[3], vec[3][3];
  jacobi3(cov, val, vec);
  int smallest = 0;
  for (int i = 1; i < 3; ++i)
    if (val[i] < val[smallest]) smallest = i;

  double nx = vec[0][smallest], ny = vec[1][smallest], nz = vec[2][smallest];
  const double len = std::sqrt(nx * nx + ny * ny + nz * nz);
  if (len > 0) { nx /= len; ny /= len; nz /= len; }
  if (nz < 0) { nx = -nx; ny = -ny; nz = -nz; }  // keep normals pointing up
  out.nx = nx; out.ny = ny; out.nz = nz;

  double sum_sq = 0.0, worst = 0.0;
  for (const auto& p : pts) {
    const double dev =
        (p[0] - cx) * nx + (p[1] - cy) * ny + (p[2] - cz) * nz;
    sum_sq += dev * dev;
    worst = std::max(worst, std::abs(dev));
  }
  out.rms = std::sqrt(sum_sq / static_cast<double>(n));
  out.max_dev = worst;
  return out;
}

Plane level_plane(double z) {
  Plane p;
  p.px = 0; p.py = 0; p.pz = z;
  p.nx = 0; p.ny = 0; p.nz = 1;
  return p;
}

Plane fit_or_level(const std::vector<Pt3>& pts, double max_tilt_deg) {
  const Plane p = fit_plane(pts);
  if (p.tilt_deg() > max_tilt_deg) {
    double s = 0.0;
    for (const auto& q : pts) s += q[2];
    return level_plane(s / static_cast<double>(pts.size()));
  }
  return p;
}

}  // namespace snapir

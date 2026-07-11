# -*- coding: utf-8 -*-

# from matplotlib import pyplot as plt
import math

import logging
logger = logging.getLogger()

# Determines if two floats are approximately equal
def almostEqual(x, y, EPSILON=1e-9):
    return abs(x - y) < EPSILON

# Determines if two floats are approximately equal
def almostZero(x, EPSILON=1e-9):
    return abs(x) < EPSILON

# Determines if two floats are approximately equal
def equalPoint(pointA, pointB, EPSILON=1e-9):
  return almostEqual(pointA[0], pointB[0], EPSILON=EPSILON) and almostEqual(pointA[1], pointB[1], EPSILON=EPSILON)

# Parse coords of various types to a (x, y) tuple
# Input -> Point, list, tuple, np.array, x, y
def parseCoords(args):
  nArgs = len(args)
  # bulge = None

  if nArgs == 1:
    x = args[0][0]
    y = args[0][1]

  elif nArgs == 2:
    x = args[0]
    y = args[1]

  # elif nArgs == 3:
  #   x = args[0]
  #   y = args[1]
  #   bulge = args[1]

  else:
    raise TypeError("Arguments can't be parsed to coordinate tuple")

  return (x, y)

def polar_point(radius, angle):
    x = radius * math.cos(angle)
    y = radius * math.sin(angle)

    return Point(x, y)



class Point(object):

  def __init__(self, *args):
    self.x, self.y = parseCoords(args)
    self.float()
    self.bulge = None


  def __getitem__(self, index):
    index = index % 2

    if index == 0:
      return self.x

    elif index == 1:
      return self.y


  def __iter__(self):
    yield self.x
    yield self.y


  def __repr__(self):
    return "Point: (" + str(self.x) + ", " + str(self.y) + ") "


  # allow addition of points as vectors
  def __add__(self, other):
    return Point(self.x + other[0], self.y + other[1])


  # allow subtraction of points as vectors
  def __sub__(self, other):
    return Point(self.x - other[0], self.y - other[1])

  # allow multiply of points with scalar
  def __mul__(self, scalar):
    return Point(self.x * scalar, self.y * scalar)

  __rmul__ = __mul__

  # allow devision of points by scalar
  def __truediv__(self, scalar):
    return Point(self.x / scalar, self.y / scalar)

  __div__ = __truediv__

  # mirrors point with regard to origin
  def __neg__(self):
    return Point(-self.x, -self.y)


  def int(self, scale=1):
    self.x = int(round(self.x * scale))
    self.y = int(round(self.y * scale))


  def float(self, scale=1):
    self.x = round(self.x / float(scale), 6)
    self.y = round(self.y / float(scale), 6)

    # if self.bulge:
    #   self.bulge = round(self.bulge, 6)


  def dot(self, other):
    return self.x * other.x + self.y * other.y


  # distance to origin
  def distance(self, squared=False):
    if squared:
      return math.pow(self.x, 2) + math.pow(self.y, 2)
    else:
      return math.hypot(self.x, self.y)


  # # distance to origin
  # def distance(self, squared=False):
  #   if squared:
  #     return math.pow(self.x, 2) + math.pow(self.y, 2)
  #   else:
  #     return math.hypot(self.x, self.y)


  # computes determinant of other with regard to self
  def determinant(self, other, normalized=False):
    det = (self.x * other[1] - self.y * other[0])
    # det = (other[0] * self.y - other[1] * self.x)

    if normalized:
      det = det / self.distance()

    return det


  # returns True if left or on Line
  def isLeftOf(self, other):
    # return self.determinant(other, normalized=True) >= 0
    return self.determinant(other, normalized=True) <= 0


  # returns True if right or on Line
  def isRightOf(self, other):
    # return self.determinant(other, normalized=True) <= 0
    return self.determinant(other, normalized=True) >= 0


  # return a tuple with x, y coordinates
  def coords(self):
    return (self.x, self.y)




class Path(object):

  # Start point form list or other path
  def __init__(self, coordsList=None):
    self.points = []

    if coordsList:
      self.setPoints(coordsList)


  def __getitem__(self, index):
    if type(index) in [int, float]:
      index = index % len(self)

    return self.points[index]


  def __iter__(self):
    for i in range(len(self)):
      yield self[i]


  def __len__(self):
    return len(self.points)


  def __repr__(self):
    string = "Path( "

    for point in self.points:
      string += "(" + str(point.x) + ", " + str(point.y) + ") "
    string += ")"

    return string


  def int(self, scale=1):
    for i in range(len(self)):
      self.points[i].int(scale)


  def float(self, scale=1):
    for i in range(len(self)):
      self.points[i].float(scale)


  # Get the minimum (lower-left bounding box point)
  def min(self):
    minX, minY = self.points[0]

    for i in range(1, len(self)):
      x, y = self.points[i]

      if x < minX:
         minX = x

      if y < minY:
         minY = y

    return Point(minX, minY)

  # Get the maximum (top-right bounding box point)
  def max(self):
    maxX, maxY = self.points[0]

    for i in range(1, len(self)):
      x, y = self.points[i]

      if x > maxX:
         maxX = x

      if y > maxY:
         maxY = y

    return Point(maxX, maxY)


  def append(self, coords):
    self.points.append(Point(coords))


  def setPoints(self, coordsList):
    for coords in coordsList:
      self.append(coords)


  def translate(self, *args):
    x, y = parseCoords(args)

    for i in range(len(self)):
      self.points[i] += (x, y)


  def reverse(self):
    self.points.reverse()

    # Take bulge into account
    for i in range(1, len(self.points)):
      if self.points[i].bulge:
        self.points[i - 1].bulge = -self.points[i].bulge
        self.points[i].bulge = None

    return


  def area(self):
    area = 0
    for i in range(len(self)):
      area += self[i].determinant(self[i + 1])

    return area / 2


  def isCCW(self):
    return self.area() >= 0


  def CCW(self):
    if not self.isCCW():
      self.reverse()


  def CW(self):
    if self.isCCW():
      self.reverse()


  def contains(self, point):
    horizon = Point((self.max().x + 1), point.y)

    nCrossings = 0
    intersections = self.intersectSegment(point, horizon)

    nInters = len(intersections)
    for i in range(nInters):
      intersection = intersections[i]
      flag = intersection[1]
      if flag == 0:
        nCrossings += 1

      elif flag == 3 and not (intersections[i - nInters + 1][1] == 4):
        nCrossings += 1

    return (nCrossings % 2 != 0)


  def centroid(self):
    x = 0
    y = 0

    for i in range(len(self)):
      point1 = self[i]
      point2 = self[i + 1]

      det = point1.determinant(point2)
      x += (point1.x + point2.x) * det
      y += (point1.y + point2.y) * det

    area = self.area()
    x = x / (6*area)
    y = y / (6*area)

    return Point(x, y)


  # Get bottom left index in a ring
  def bottomLeftIndex(self):
    index = 0
    xMin = float('Inf')
    yMin = float('Inf')

    for i in range(len(self)):
      point = self[i]

      if point.y < yMin:
        index = i
        xMin = point.x
        yMin = point.y

      elif (point.y == yMin) and (point.x < xMin):
        index = i
        xMin = point.x

    return index


  #  Get top right index in a ring
  def topRightIndex(self):
    index = 0
    xMax = -float('Inf')
    yMax = -float('Inf')

    for i in range(len(self)):
      point = self[i]

      if point.y > yMax:
        index = i
        xMax = point.x
        yMax = point.y

      elif (point.y == yMax) and (point.x > xMax):
        index = i
        xMax = point.x

    return index


  # Compute the orientation predicate of all point of two rings
  def determinants(self, point, normalized=False):
    dets = []
    for i in range(len(self)):
      point1 =  point - self[i]
      point2 =  self[i + 1] - self[i]

      det = point1.determinant(point2, normalized=normalized)
      dets.append(det)

    return dets


  # Intersect segment with lines of Path. Excluding point B of segment
  # flag = 0, orbiting crosses stationary
  # flag = 1, orbiting start on stationary start
  # flag = 2, orbiting start along stationary
  # flag = 3, stationary start along orbiting
  def intersectSegment(self, pointA, pointB):
    n = len(self)
    intersections = []

    # Determine orientation predicament of pointA and pointB
    detsA = self.determinants(pointA, normalized=False)
    detsB = self.determinants(pointB, normalized=False)

    for i in range(n):
      flag = -1
      selfA = self[i]
      selfB = self[i + 1]

      # point A of segment touches line
      if almostZero(detsA[i]):
        intersection = pointA

        # Dot and squared distance of vertex
        dot = (pointA[0] - selfA[0]) * (selfB[0] - selfA[0]) + (pointA[1] - selfA[1])*(selfB[1] - selfA[1])
        dist2 = (selfB - selfA).distance(squared=True)

        # segment Point A on line start
        if equalPoint(selfA, pointA):
          flag = 1
          intersections.append([intersection, flag, i])
          logger.debug("Segment start on line start")
          # print "[+] Segment start on line start"

        # segment point A along line
        # http://stackoverflow.com/questions/328107/how-can-you-determine-a-point-is-between-two-other-points-on-a-line-segment
        elif (dot >= 0) and (dot < dist2):
          flag = 2
          intersections.append([intersection, flag, i])
          logger.debug("Segment start on line")
          # print "[+] Segment start on line"

        # segment aligned with line
        if almostZero(detsB[i]) and (not equalPoint(selfA, pointA)) and (not equalPoint(selfA, pointB)) and (not equalPoint(selfB, pointB)):
          # Dot and squared distance of segment
          dot = (selfA[0] - pointA[0]) * (pointB[0] - pointA[0]) + (selfA[1] - pointA[1])*(pointB[1] - pointA[1])
          dist2 = (pointB - pointA).distance(squared=True)


          # line start lies on segment
          if (dot >= 0) and (dot < dist2):
            logger.debug("Line start on segment (aligned)")
            # print "[+] Line start on segment (aligned)"
            flag = 4
            intersection = selfA
            intersections.append([intersection, flag, i])


      # Crossing of line by segment
      elif ((detsA[i] * detsB[i]) < 0) and (not almostZero(detsB[i])):

        dSelf = selfB - selfA
        dSeg =  pointB - pointA

        # Compute determinant and it's inverse
        det = dSeg.determinant(dSelf)

        # Solve set of linear equations
        r = (-dSeg[1]  * (pointA[0] - selfA[0]) +  dSeg[0] * (pointA[1] - selfA[1])) / det
        s = (-dSelf[1] * (pointA[0] - selfA[0]) + dSelf[0] * (pointA[1] - selfA[1])) / det

        # Test if segment lies on start or end of vertex
        if almostZero(r):
          logger.debug("Line start on segment")
          # print "[+] Line start on segment"
          flag = 3
          intersection = selfA
          intersections.append([intersection, flag, i])

        elif (not almostEqual(r, 1)) and (r > 0) and (r < 1):
          flag = 0
          logger.debug("Segments crosses line: " + str(i))
          # print "[+] Segments crosses line:", i
          intersection = (selfA + r * dSelf + pointA + s * dSeg) / 2
          intersections.append([intersection, flag, i])

    return intersections

  # Intersection points of two Paths
  def intersectPaths(self, other):
    n = len(other)
    intersections = []
    # intersections = np.empty(shape=[0, 5])

    for i in range(n):
      otherA = other[i]
      otherB = other[i + 1]

      for intersection in self.intersectSegment(otherA, otherB):
        intersection.append(i)
        intersections.append(intersection)

    return intersections


  # Determine if entity is closed
  def isClosed(self, EPSILON=1e-4):
    return equalPoint(self[0], self[-1], EPSILON=EPSILON)







# ENTITY CLASS - A drawing entity being point, circle, polyline, path
#########################################################################################
#########################################################################################
#########################################################################################
#########################################################################################
class Entity(Path):

  def __init__(self, TOLLERANCE=0.1, *args):
    super(Entity, self).__init__(args)

    # entityType = point, circle, path
    # self.operations = []

    self.type = None
    self.approximation = None

    self.layer = None
    self.color = None
    self.radius = None
    self.TOLLERANCE = TOLLERANCE


  # Joining two entities = join points and type
  def __add__(self, other):
    sumEntity = Entity()
    sumEntity.layer = self.layer

    # Upgrade type
    if (self.type in ["LINE", "POLYLINE"]) and (other.type in ["LINE", "POLYLINE"]):
      sumEntity.type = "POLYLINE"

    else:
      sumEntity.type = "PATH"

    sumEntity.points = self.points[:-1] + other.points
    return sumEntity

  def area(self):
    area = 0

    if self.isClosed():
      approximation = self.approximate()

      for i in range(len(approximation)):
        area += approximation[i].determinant(approximation[i + 1])

    return abs(area / 2)


  def length(self):
    length = 0
    approximation = self.approximate()

    if self.isClosed():
      for i in range(len(approximation)):
        length += (approximation[i + 1] - approximation[i]).distance(squared=False)

    else:
      for i in range(len(approximation) - 1):
        length += (approximation[i + 1] - approximation[i]).distance(squared=False)


    return length


  def approximate(self):
    # return already parsed approximations
    # if self.approximation:
    #   return self.approximation

    # return self for linear types
    if self.type in ["POINT", "LINE", "SPLINE", "POLYLINE"]:
      return self

    # compute approximation
    elif not self.approximation:

      # Handle circle
      if self.type == "CIRCLE":

        tolRadius = min(self.TOLLERANCE / self.radius, 1)
        maxAngle = 2 * math.acos(1 - tolRadius)
        angle = 2 * math.pi

        nParts = int(math.ceil(angle / maxAngle))
        nParts = min(nParts, 4)
        dAngle = angle / nParts

        self.approximation = Entity()
        for i in range(nParts):
          point = [self.centroid[0] + self.radius * math.cos(i * dAngle)]
          point.append(self.centroid[1] + self.radius * math.sin(i * dAngle))

          self.approximation.append(point)
        self.approximation.append(self.approximation[0])


      # Parse bulges
      elif self.type in ["ARC", "PATH"]:
        # print "APPROXIMATION length:", len(self)

        prevPoint = self[0]
        self.approximation = Entity()
        self.approximation.append(prevPoint)

        for i in range(1, len(self)):
          point = self[i]

          if prevPoint.bulge:
            bulge = prevPoint.bulge

            # vertex parameters
            vertex = (point - prevPoint)
            length = vertex.distance()
            vertexAngle = math.atan2(vertex.y, vertex.x)

            # compute center and radius of bulge
            sagitta = length / 2 * abs(bulge)
            radius = (math.pow(length / 2, 2) + math.pow(sagitta, 2)) / (2 * sagitta)
            angle = 4.0 * math.atan(bulge)

            if bulge < 0:
              center = point + polar_point(radius, vertexAngle - math.pi / 2 + math.atan(bulge) * 2)
              bulgeSign = -1
            else:
              center = point - polar_point(radius, vertexAngle - math.pi / 2 + math.atan(bulge) * 2)
              bulgeSign = 1

            interPoint = prevPoint - center
            start = math.atan2(interPoint.y, interPoint.x)

            # approximation
            tolRadius = min(self.TOLLERANCE / radius, 1)
            maxAngle = 2 * math.acos(1 - self.TOLLERANCE/radius)
            nParts = int(math.ceil(abs(angle / maxAngle)))
            dAngle = angle / nParts

            # print "APPROXIMATION:", nParts

            # self.approximation.append(center)
            for i in range(1, nParts):
              approxPoint = [center[0] + radius * math.cos(i * dAngle + start)]
              approxPoint.append(center[1] + radius * math.sin(i * dAngle + start))
              self.approximation.append(approxPoint)

          self.approximation.append(point)
          prevPoint = point

    # Return approximation fresh or old
    return self.approximation



  # Return d parameter for a SVG path element
  def svgPath(self):
    # ["POINT", "CIRCLE", "LINE", "ARC", "SPLINE", "POLYLINE"]
    prevPoint = self[0]
    d = "M %f %f " %(prevPoint.x, prevPoint.y)

    for i in range(1, len(self)):
      point = self[i]

      # Parse a bulge
      if prevPoint.bulge:
        bulge = prevPoint.bulge
        length = (point - prevPoint).distance()
        sagitta = length / 2 * bulge
        radius = (math.pow(length / 2, 2) + math.pow(sagitta, 2)) / (2 * sagitta)

        largeArcSweep = (abs(bulge) > 1)
        sweepFlag = (bulge >= 0)

        d += "A %f %f 0 %d %d %f %f" %(radius, radius, int(largeArcSweep), int(sweepFlag), point.x, point.y)

      # Draw straight line
      else:
        d += "L %f %f" %(point.x, point.y)

      prevPoint = point

    # Close if closed
    if self.isClosed():
      d += "Z"

    return d










# PART CLASS - Part class everything of a single part
#########################################################################################
#########################################################################################
#########################################################################################
#########################################################################################
class Part(object):

  def __init__(self, contour=None, *args):
    # Init contour
    self.name = None
    self.contour = contour
    self.holes = []
    self.other = []




# # Temp function to plot progress
# def plotPaths(ax, *args):
#   for path in args:
#     xCoords = [path[-1].x]
#     yCoords = [path[-1].y]

#     for i in range(len(path)):
#       x, y = path[i]
#       xCoords.append(x)
#       yCoords.append(y)

#       ax.annotate(i, (x, y))

#     # Plot edge
#     ax.plot(xCoords, yCoords, linewidth=1)

#     # Plot centroid
#     circle = plt.Circle(path.centroid(), 0.05, color='b')
#     ax.add_artist(circle)


# # Temp function to plot progress
# def plotProgress(ax, paths, nfp):
#   for path in paths:
#     xCoords = [path[-1].x]
#     yCoords = [path[-1].y]

#     for i in range(len(path)):
#       x, y = path[i]
#       xCoords.append(x)
#       yCoords.append(y)
#       # ax.annotate(i, (x, y))

#     # Plot edge
#     ax.plot(xCoords, yCoords, linewidth=1)

#     # Plot centroid
#     # circle = plt.Circle(path.centroid(), 0.05, color='b')
#     # ax.add_artist(circle)

#   xCoords = []
#   yCoords = []
#   for i in range(len(nfp)):
#     x, y = nfp[i]
#     xCoords.append(x)
#     yCoords.append(y)
#     # ax.annotate(i, (x, y))

#   ax.plot(xCoords, yCoords, linewidth=1)


# # Temp function to plot progress
# def plotIntersections(ax, inters, radius=0.05):
#   for inter in inters:
#     circle = plt.Circle(inter, radius, color='r')
#     ax.add_artist(circle)

# def vectorize(image):
#   vector = []







def main():
  ###############################################
  ## Tests Point Class ##########################
  ###############################################
  print("[+] Testing Point Class")

  p1 = Point([1, 2])
  print(" | init:", p1)
  print(" | index:", p1[-1], p1[0], p1[1], p1[2])

  string = " | iter:"
  for coord in p1:
    string += " " + str(coord)
  print(string)

  print(" | add:", p1 + p1, p1 + [1, 2], p1 + (1, 2))
  print(" | sub:", p1 - p1, p1 - [1, 2], p1 - (1, 2))
  print(" | neg:", -p1)
  print(" | div:", p1 / 2.0)
  print(" | distance", p1.distance())
  print(" | determinant", p1.determinant(p1), p1.determinant(p1 + (0, 1), normalized=True), p1.determinant(p1 + (0, -1), normalized=True))
  print(" | orientation", p1.isRightOf((0, 1)), p1.isLeftOf((0, -1)))


  ###############################################
  ## Tests Path Class ###########################
  ###############################################
  print("\n[+] Testing Path Class")
  contour1 = [[0., 0.], [10., 0.], [10., 10.]]
  path1 = Path(contour1)

  print(" | init:", path1)
  print(" | index:", path1[-1], path1[0], path1[1], path1[2])

  string = " | iter:"
  for point in path1:
    string += " " + str(point)
  print(string)

  path1.append([0., 10.])
  print(" | append:", path1)
  print(" | contains:", path1.contains(Point(-15., 5.)), path1.contains(Point(5., 5.)))

  path1.translate(1., 2.)
  print(" | translate:", path1)

  path1.reverse()
  print(" | reverse:", path1)
  print(" | area:", path1.area())
  print(" | isCCW:", path1.isCCW())

  path1.CCW()
  print(" | CCW:", path1)

  centroid = path1.centroid()
  print(" | centroid:", centroid)
  print(" | bottom left:", path1.bottomLeftIndex())
  print(" | top right:", path1.topRightIndex())
  print(" | determinants:", path1.determinants(centroid))
  print(" | intersection segment:", path1.intersectSegment(Point(0., 3.), Point(3., 1.)))

  contour2 = [[0., 5.], [5., 5.], [5., 0.], [0., 0.]]
  path2 = Path(contour2)
  print(" | intersection paths:", path1.intersectPaths(path2))




if __name__ == '__main__':
  main()
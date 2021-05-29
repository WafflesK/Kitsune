"""
Add primary keys to discord_posts
"""

from yoyo import step

__depends__ = {'20210328_01_8tlz4-add-indexes-to-favorites-tables'}

steps = [
    step("ALTER TABLE discord_posts ADD PRIMARY KEY (id, server); ")
]

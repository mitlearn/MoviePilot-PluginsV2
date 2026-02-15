# -*- coding: utf-8 -*-
"""
Schema definitions for JackettIndexer agent tools
"""

from pydantic import BaseModel, Field


class SearchTorrentsToolInput(BaseModel):
    """搜索种子工具输入参数"""
    explanation: str = Field(
        ...,
        description="Explanation of why you are using this tool to search for torrents"
    )
    keyword: str = Field(
        ...,
        description="Search keyword or IMDb ID (e.g., 'The Matrix' or 'tt0133093')"
    )
    mtype: str | None = Field(
        default=None,
        description="Media type filter: 'movie' or 'tv'. Leave empty to search both."
    )
    indexer_name: str | None = Field(
        default=None,
        description="Specific Jackett indexer name to search. Leave empty to search all indexers."
    )


class ListIndexersToolInput(BaseModel):
    """列出索引器工具输入参数"""
    explanation: str = Field(
        ...,
        description="Explanation of why you want to list available indexers"
    )
